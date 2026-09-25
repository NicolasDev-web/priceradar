import json
import logging
import statistics
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models_db import BuscaSalva, EmpreendimentoDB
from models import BuscaRequest, BuscaResponse, Empreendimento

logger = logging.getLogger(__name__)


def _ler_fotos(bruto: str | None) -> list[str]:
    """Desserializa a coluna `fotos`. Linha antiga (NULL) ou JSON corrompido
    vira lista vazia: o card cai na imagem genérica em vez de a busca quebrar."""
    if not bruto:
        return []
    try:
        fotos = json.loads(bruto)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Coluna fotos com JSON inválido; tratando como sem foto")
        return []
    return [f for f in fotos if isinstance(f, str)] if isinstance(fotos, list) else []


def _chave_bairros(request) -> str | None:
    """
    Bairros normalizados e ordenados numa string, para a chave de cache.

    Sem ordenar, buscar "Aldeota, Meireles" e "Meireles, Aldeota" seriam duas
    entradas diferentes no cache para a mesma pergunta.
    """
    bairros = getattr(request, 'lista_bairros', None)
    if bairros is None:
        b = getattr(request, 'bairro', None)
        bairros = [b] if b else []
    if not bairros:
        return None
    return ','.join(sorted(b.strip().lower() for b in bairros if b and b.strip()))


async def salvar_busca(db: AsyncSession, busca: BuscaRequest, resultado: BuscaResponse) -> str:
    nova = BuscaSalva(
        cidade=busca.cidade,
        preco_min=busca.preco_min,
        preco_max=busca.preco_max,
        quartos=busca.quartos,
        bairro=_chave_bairros(busca),
        banheiros=busca.banheiros,
        tipo_edificacao=busca.tipo_edificacao,
        total_encontrado=resultado.total,
        preco_m2_medio=resultado.preco_m2_medio,
        preco_m2_mediana=resultado.preco_m2_mediana,
    )
    db.add(nova)
    await db.flush()

    for emp in resultado.empreendimentos:
        db.add(EmpreendimentoDB(
            busca_id=nova.id,
            nome_anuncio=emp.nome_anuncio,
            nome_empreendimento=emp.nome_empreendimento,
            construtora=emp.construtora,
            cidade=emp.cidade,
            bairro=emp.bairro,
            endereco=emp.endereco,
            tipo_edificacao=emp.tipo_edificacao,
            latitude=emp.latitude,
            longitude=emp.longitude,
            origem_coordenada=emp.origem_coordenada,
            portal=emp.portal,
            preco=emp.preco,
            area_m2=emp.area_m2,
            preco_m2=emp.preco_m2,
            variacao_mrv_pct=emp.variacao_mrv_pct,
            quartos=emp.quartos,
            banheiros=emp.banheiros,
            vagas=emp.vagas,
            descricao=emp.descricao,
            url_anuncio=emp.url_anuncio,
            data_coleta=emp.data_coleta,
            rf_score=emp.rf_score,
            fotos=json.dumps(emp.fotos) if emp.fotos else None,
        ))

    await db.commit()
    return nova.id


def _mesma_busca(q, request: BuscaRequest):
    """Restringe a consulta às buscas com os mesmos parâmetros que mudam o
    resultado. Usado pelo cache e pela comparação com a busca anterior.
    Todos podem ser None — comparação explícita (== None vira IS NULL)."""
    return q.where(
        BuscaSalva.cidade == request.cidade,
        BuscaSalva.preco_min == request.preco_min,
        BuscaSalva.preco_max == request.preco_max,
        BuscaSalva.quartos == request.quartos,
        BuscaSalva.banheiros == request.banheiros,
        BuscaSalva.bairro == _chave_bairros(request),
        BuscaSalva.tipo_edificacao == request.tipo_edificacao,
    )


async def buscar_anterior(db: AsyncSession, request: BuscaRequest, pular: int = 0) -> BuscaSalva | None:
    """
    A busca igual mais recente já gravada, com os anúncios carregados — base
    dos selos "Novo" e "preço caiu/subiu". `pular=1` ignora a mais recente
    (quando ela é o próprio cache que está sendo devolvido).
    """
    q = _mesma_busca(select(BuscaSalva), request).where(BuscaSalva.total_encontrado > 0)
    q = q.order_by(BuscaSalva.criado_em.desc()).offset(pular).limit(1).options(selectinload(BuscaSalva.empreendimentos))
    return (await db.execute(q)).scalar_one_or_none()


async def buscar_cache_recente(
    db: AsyncSession,
    request: BuscaRequest,
    minutos_validade: int,
    preco_m2_mrv: float | None = None,
) -> BuscaResponse | None:
    """
    Procura uma busca idêntica (mesmos cidade/preço/quartos/banheiros/bairro/
    tipo de edificação) feita há menos
    de `minutos_validade` minutos. Se achar, reconstrói o BuscaResponse a partir do
    banco — evitando refazer o scraping. Retorna None se não houver cache válido.
    """
    limite = datetime.utcnow() - timedelta(minutes=minutos_validade)
    # Todo filtro que muda o resultado está em _mesma_busca: `tipo_edificacao`
    # já faltou aqui, e uma busca "só torre" saía do cache sem filtro nenhum.
    q = (
        _mesma_busca(select(BuscaSalva), request)
        .where(BuscaSalva.criado_em >= limite, BuscaSalva.total_encontrado > 0)
        .order_by(BuscaSalva.criado_em.desc())
        .options(selectinload(BuscaSalva.empreendimentos))
        .limit(1)
    )

    result = await db.execute(q)
    busca = result.scalar_one_or_none()
    if busca is None:
        return None

    empreendimentos = []
    for e in busca.empreendimentos:
        variacao = None
        if preco_m2_mrv and preco_m2_mrv > 0:
            variacao = round(((e.preco_m2 - preco_m2_mrv) / preco_m2_mrv) * 100, 1)
        empreendimentos.append(Empreendimento(
            id=e.id,
            nome_anuncio=e.nome_anuncio,
            nome_empreendimento=e.nome_empreendimento,
            construtora=e.construtora,
            cidade=e.cidade,
            bairro=e.bairro,
            endereco=e.endereco,
            tipo_edificacao=e.tipo_edificacao,
            # Sem estes três o cache hit devolveria um mapa vazio enquanto a
            # busca fresca mostra os pinos — a mesma pergunta com duas respostas.
            latitude=e.latitude,
            longitude=e.longitude,
            origem_coordenada=e.origem_coordenada,
            portal=e.portal,
            preco=e.preco,
            area_m2=e.area_m2,
            preco_m2=e.preco_m2,
            preco_m2_mrv=preco_m2_mrv,
            variacao_mrv_pct=variacao,
            quartos=e.quartos,
            banheiros=e.banheiros,
            vagas=e.vagas,
            descricao=e.descricao,
            url_anuncio=e.url_anuncio,
            data_coleta=e.data_coleta,
            rf_score=e.rf_score,
            fotos=_ler_fotos(e.fotos),
        ))

    empreendimentos.sort(key=lambda x: x.preco_m2)
    precos_m2 = [x.preco_m2 for x in empreendimentos]
    return BuscaResponse(
        total=len(empreendimentos),
        preco_m2_medio=round(sum(precos_m2) / len(precos_m2), 2) if precos_m2 else 0.0,
        # Recalcula a mediana a partir dos itens: buscas gravadas antes desta
        # coluna existir têm preco_m2_mediana nulo no banco.
        preco_m2_mediana=round(statistics.median(precos_m2), 2) if precos_m2 else 0.0,
        preco_m2_min=min(precos_m2) if precos_m2 else 0.0,
        preco_m2_max=max(precos_m2) if precos_m2 else 0.0,
        preco_m2_mrv=preco_m2_mrv,
        empreendimentos=empreendimentos,
        tempo_coleta_segundos=0.0,
        sem_localizacao=sum(1 for x in empreendimentos if x.latitude is None),
    )


async def listar_buscas(db: AsyncSession, cidade: str | None = None, limit: int = 20) -> list[BuscaSalva]:
    q = select(BuscaSalva).order_by(BuscaSalva.criado_em.desc()).limit(limit)
    if cidade:
        q = q.where(BuscaSalva.cidade.ilike(f"%{cidade.split(',')[0].strip()}%"))
    result = await db.execute(q)
    return list(result.scalars().all())


async def buscar_por_id(db: AsyncSession, busca_id: str) -> BuscaSalva | None:
    q = select(BuscaSalva).where(BuscaSalva.id == busca_id).options(selectinload(BuscaSalva.empreendimentos))
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def deletar_busca(db: AsyncSession, busca_id: str) -> bool:
    busca = await buscar_por_id(db, busca_id)
    if not busca:
        return False
    await db.delete(busca)
    await db.commit()
    return True
