from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models_db import BuscaSalva, EmpreendimentoDB, ReferencialMRV
from scraper.rsc_grupozap import chave_url
from services.texto import normalizar


async def listar_por_cidade(db: AsyncSession, cidade: str, limit: int = 100) -> list[EmpreendimentoDB]:
    q = (
        select(EmpreendimentoDB)
        .where(EmpreendimentoDB.cidade.ilike(f"%{cidade.lower()}%"))
        .order_by(EmpreendimentoDB.data_coleta.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


def _chave_cidade(cidade: str) -> str:
    """"Fortaleza, CE", "fortaleza,ce" e "Fortaleza , CE" viram a mesma chave."""
    return ",".join(p.strip() for p in normalizar(cidade or "").split(","))


async def _cidades_gravadas(db: AsyncSession, cidade: str) -> list[str]:
    """
    Grafias de `buscas.cidade` que correspondem à cidade pedida.

    A comparação é feita em Python, com `normalizar`, porque o ILIKE do SQLite
    só ignora caixa de letras ASCII ("SÃO PAULO" não casa "são paulo"). A lista
    de cidades distintas é minúscula, então trazê-la inteira é barato. Pedido
    sem UF ("Fortaleza") casa só pelo nome; com UF, a UF também precisa bater
    — senão "Bom Jesus, PI" misturaria com "Bom Jesus, RS".
    """
    pedida = _chave_cidade(cidade)
    if not pedida:
        return []
    so_nome = "," not in pedida
    gravadas = (await db.execute(select(BuscaSalva.cidade).distinct())).scalars().all()
    return [
        c for c in gravadas
        if (_chave_cidade(c).split(",")[0] if so_nome else _chave_cidade(c)) == pedida
    ]


async def observacoes_por_periodo(db: AsyncSession, cidade: str, quartos: int | None) -> list[dict]:
    """
    Base de toda série histórica: um anúncio por período, com a observação mais
    recente dele naquele período.

    Por que não filtrar `EmpreendimentoDB.cidade`: o anúncio é gravado com a
    cidade normalizada ("fortaleza") e a busca com a grafia do formulário
    ("Fortaleza, CE") — o filtro antigo misturava as duas e nunca casava. A
    cidade vem da busca (join com `buscas`), que é o que o usuário pediu.

    Por que deduplicar: cada busca grava de novo os anúncios que encontrou. Sem
    isso, um anúncio visto em 5 buscas na semana pesava 5 vezes na média (no
    banco de teste, 33 linhas para 12 anúncios). A chave é a URL normalizada
    (`chave_url`), a mesma usada na comparação entre buscas.

    Período = semana '%Y-W%W' (segunda-feira como início, igual ao strftime do
    SQLite que a versão antiga usava) — o frontend formata esse texto.
    """
    cidades = await _cidades_gravadas(db, cidade)
    if not cidades:
        return []
    q = (
        select(
            EmpreendimentoDB.url_anuncio,
            EmpreendimentoDB.bairro,
            EmpreendimentoDB.preco_m2,
            EmpreendimentoDB.data_coleta,
            BuscaSalva.criado_em,
        )
        .join(BuscaSalva, EmpreendimentoDB.busca_id == BuscaSalva.id)
        .where(BuscaSalva.cidade.in_(cidades), EmpreendimentoDB.preco_m2 > 0)
    )
    if quartos:
        # Quartos do anúncio, não da busca: busca sem filtro de quartos também
        # traz anúncios de 2 quartos, e eles valem para a série de 2 quartos.
        q = q.where(EmpreendimentoDB.quartos == quartos)

    mais_recente: dict[tuple[str, str], dict] = {}
    for url, bairro, preco_m2, data_coleta, criado_em in (await db.execute(q)).all():
        # data_coleta é quando o anúncio foi visto; linha antiga sem ela usa a
        # data da busca, que é praticamente o mesmo instante.
        quando = data_coleta or criado_em
        if quando is None:
            continue
        semana = quando.strftime("%Y-W%W")
        chave = (semana, chave_url(url) or url)
        atual = mais_recente.get(chave)
        if atual is None or quando > atual["quando"]:
            mais_recente[chave] = {
                "semana": semana, "url": chave[1], "bairro": bairro,
                "preco_m2": float(preco_m2), "quando": quando,
            }
    return sorted(mais_recente.values(), key=lambda o: (o["semana"], o["url"]))


async def preco_m2_historico(db: AsyncSession, cidade: str, quartos: int | None) -> list[dict]:
    """Evolução por cidade (EvolucaoChart). Mesmo formato de antes; a base
    agora é `observacoes_por_periodo` — cidade via busca e sem contagem dupla."""
    por_semana: dict[str, list[float]] = {}
    for o in await observacoes_por_periodo(db, cidade, quartos):
        por_semana.setdefault(o["semana"], []).append(o["preco_m2"])
    return [
        {"semana": s, "preco_m2_medio": round(sum(v) / len(v), 2), "total": len(v)}
        for s, v in sorted(por_semana.items())
    ]


async def upsert_referencial_mrv(
    db: AsyncSession, cidade: str, produto: str, quartos: int | None, preco_m2: float
) -> None:
    from datetime import datetime
    q = select(ReferencialMRV).where(
        ReferencialMRV.cidade.ilike(f"%{cidade.lower()}%"),
        ReferencialMRV.quartos == quartos,
    )
    result = await db.execute(q)
    existente = result.scalar_one_or_none()

    if existente:
        existente.produto = produto
        existente.preco_m2 = preco_m2
        existente.atualizado_em = datetime.utcnow()
    else:
        db.add(ReferencialMRV(cidade=cidade.lower(), produto=produto, quartos=quartos, preco_m2=preco_m2))

    await db.commit()


async def get_referencial_mrv(db: AsyncSession, cidade: str, quartos: int | None) -> float | None:
    q = (
        select(ReferencialMRV.preco_m2)
        .where(ReferencialMRV.cidade.ilike(f"%{cidade.split(',')[0].strip().lower()}%"))
        .order_by(ReferencialMRV.atualizado_em.desc())
        .limit(1)
    )
    if quartos:
        q = q.where(ReferencialMRV.quartos == quartos)
    result = await db.execute(q)
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None
