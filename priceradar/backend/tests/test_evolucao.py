"""Evolução do preço/m² por cidade e por bairro, a partir do histórico gravado.

O que importa travar:
- a cidade vem da busca ("Fortaleza, CE"), não do anúncio ("fortaleza") — o
  filtro antigo misturava as duas e a série voltava sempre vazia;
- o mesmo anúncio visto em várias buscas da semana conta uma vez só;
- ponto com menos de 3 anúncios sai marcado como pouco confiável;
- "Aldeota" e "aldeóta" são o mesmo bairro;
- o filtro de quartos vale;
- o endpoint devolve o formato combinado com o frontend.
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("SECRET_KEY", "chave-de-teste")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from database import models_db  # noqa: E402,F401
from database.connection import Base, get_db  # noqa: E402
from database.models_db import BuscaSalva, EmpreendimentoDB  # noqa: E402
from models import BuscaRequest, BuscaResponse, Empreendimento  # noqa: E402
from repositories.busca_repo import salvar_busca  # noqa: E402
from repositories.empreendimento_repo import observacoes_por_periodo, preco_m2_historico  # noqa: E402
from services.evolucao import ler_lista_bairros, serie_por_bairro  # noqa: E402

# Duas segundas-feiras seguidas: semanas '%Y-W%W' diferentes.
SEMANA_1 = datetime(2026, 9, 7, 10, 0)
SEMANA_2 = datetime(2026, 9, 14, 10, 0)


def req(**kw):
    base = {"cidade": "Fortaleza, CE", "preco_min": 200_000, "preco_max": 900_000, "quartos": None}
    base.update(kw)
    return BuscaRequest(**base)


def emp(url, preco_m2, bairro="Meireles", quartos=2, quando=SEMANA_1, cidade="fortaleza"):
    # Anúncio gravado como o scraper grava: cidade normalizada, sem UF.
    return Empreendimento(
        id=url, nome_anuncio="Apto", nome_empreendimento=None, construtora=None, cidade=cidade,
        bairro=bairro, portal="vivareal", preco=preco_m2 * 60, area_m2=60, preco_m2=preco_m2,
        quartos=quartos, banheiros=1, vagas=1, descricao=None, url_anuncio=url, data_coleta=quando,
    )


def resposta(emps):
    return BuscaResponse(total=len(emps), preco_m2_medio=7000, preco_m2_min=6000, preco_m2_max=8000,
                         empreendimentos=emps, tempo_coleta_segundos=1)


async def gravar(db, emps, quando=SEMANA_1, **kw):
    """Salva uma busca e alinha `criado_em` à semana desejada — o default é agora."""
    busca_id = await salvar_busca(db, req(**kw), resposta(emps))
    await db.execute(update(BuscaSalva).where(BuscaSalva.id == busca_id).values(criado_em=quando))
    await db.commit()
    return busca_id


def com_banco(corpo):
    async def rodar():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await corpo(db)
        finally:
            await engine.dispose()
    return asyncio.run(rodar())


# ── F6.1: base corrigida ───────────────────────────────────────────────────────

def test_cidade_da_busca_casa_mesmo_com_anuncio_gravado_sem_uf():
    async def corpo(db):
        await gravar(db, [emp("https://vr/1", 7000), emp("https://vr/2", 8000)])
        serie = await preco_m2_historico(db, "Fortaleza, CE", None)
        assert serie == [{"semana": "2026-W36", "preco_m2_medio": 7500.0, "total": 2, "pouco_confiavel": True}]
        # Variações de grafia da mesma cidade também casam.
        assert await preco_m2_historico(db, "fortaleza,ce", None) == serie
        assert await preco_m2_historico(db, "Fortaleza", None) == serie
        # Outra UF não.
        assert await preco_m2_historico(db, "Fortaleza, RN", None) == []
    com_banco(corpo)


def test_cidade_do_anuncio_nao_e_usada_como_filtro():
    async def corpo(db):
        # Busca de Recife que por acaso gravou anúncio com cidade "fortaleza":
        # quem manda é a busca, não o texto do anúncio.
        await gravar(db, [emp("https://vr/1", 7000)], cidade="Recife, PE")
        assert await preco_m2_historico(db, "Fortaleza, CE", None) == []
        assert len(await preco_m2_historico(db, "Recife, PE", None)) == 1
    com_banco(corpo)


def test_mesmo_anuncio_em_varias_buscas_conta_uma_vez_por_semana():
    async def corpo(db):
        # Três buscas na mesma semana veem o anúncio 1; a última com preço novo.
        await gravar(db, [emp("https://vr/1", 7000), emp("https://vr/2", 9000)])
        await gravar(db, [emp("https://vr/1/?utm=x", 7000, quando=datetime(2026, 9, 8))],
                     quando=datetime(2026, 9, 8), preco_max=800_000)
        await gravar(db, [emp("https://vr/1/", 6000, quando=datetime(2026, 9, 9))],
                     quando=datetime(2026, 9, 9), preco_max=700_000)
        obs = await observacoes_por_periodo(db, "Fortaleza, CE", None)
        assert len(obs) == 2
        por_url = {o["url"]: o["preco_m2"] for o in obs}
        # Fica a observação mais recente (6000), não a primeira nem a média.
        assert por_url == {"https://vr/1": 6000.0, "https://vr/2": 9000.0}
        serie = await preco_m2_historico(db, "Fortaleza, CE", None)
        assert serie == [{"semana": "2026-W36", "preco_m2_medio": 7500.0, "total": 2, "pouco_confiavel": True}]
    com_banco(corpo)


def test_mesmo_anuncio_em_semanas_diferentes_conta_em_cada_uma():
    async def corpo(db):
        await gravar(db, [emp("https://vr/1", 7000)])
        await gravar(db, [emp("https://vr/1", 7700, quando=SEMANA_2)], quando=SEMANA_2, preco_max=800_000)
        serie = await preco_m2_historico(db, "Fortaleza, CE", None)
        assert [(p["semana"], p["preco_m2_medio"], p["total"]) for p in serie] == [
            ("2026-W36", 7000.0, 1), ("2026-W37", 7700.0, 1),
        ]
    com_banco(corpo)


def test_semana_da_cidade_com_poucos_anuncios_sai_marcada():
    async def corpo(db):
        await gravar(db, [emp(f"https://vr/{i}", 7000) for i in range(3)])
        await gravar(db, [emp("https://vr/9", 7700, quando=SEMANA_2)], quando=SEMANA_2, preco_max=800_000)
        serie = await preco_m2_historico(db, "Fortaleza, CE", None)
        assert [(p["total"], p["pouco_confiavel"]) for p in serie] == [(3, False), (1, True)]
    com_banco(corpo)


def test_linha_antiga_sem_data_coleta_usa_data_da_busca():
    async def corpo(db):
        busca_id = await gravar(db, [emp("https://vr/1", 7000)], quando=SEMANA_2)
        await db.execute(update(EmpreendimentoDB).where(EmpreendimentoDB.busca_id == busca_id)
                         .values(data_coleta=None))
        await db.commit()
        serie = await preco_m2_historico(db, "Fortaleza, CE", None)
        assert [p["semana"] for p in serie] == ["2026-W37"]
    com_banco(corpo)


def test_filtro_de_quartos():
    async def corpo(db):
        await gravar(db, [emp("https://vr/1", 7000, quartos=2), emp("https://vr/2", 9000, quartos=3)])
        assert (await preco_m2_historico(db, "Fortaleza, CE", 2))[0]["preco_m2_medio"] == 7000.0
        assert (await preco_m2_historico(db, "Fortaleza, CE", 3))[0]["preco_m2_medio"] == 9000.0
        assert (await preco_m2_historico(db, "Fortaleza, CE", None))[0]["total"] == 2
    com_banco(corpo)


# ── F6.2: série por bairro ─────────────────────────────────────────────────────

def obs(url, preco_m2, bairro, semana="2026-W36"):
    return {"semana": semana, "url": url, "bairro": bairro, "preco_m2": preco_m2}


def test_media_mediana_e_n_por_bairro_e_semana():
    r = serie_por_bairro([
        obs("a", 6000, "Meireles"), obs("b", 7000, "Meireles"), obs("c", 11000, "Meireles"),
        obs("d", 5000, "Meireles", semana="2026-W37"),
    ])
    (meireles,) = r["bairros"]
    assert meireles["bairro"] == "Meireles" and meireles["total"] == 4
    p1, p2 = meireles["serie"]
    assert (p1["semana"], p1["preco_m2_medio"], p1["preco_m2_mediana"], p1["n"]) == ("2026-W36", 8000.0, 7000.0, 3)
    assert r["periodos"] == ["2026-W36", "2026-W37"]
    # Amostra mínima: 3 é confiável, 1 não.
    assert p1["pouco_confiavel"] is False
    assert p2["pouco_confiavel"] is True and p2["n"] == 1
    assert r["min_amostra"] == 3


def test_bairro_com_e_sem_acento_e_o_mesmo():
    r = serie_por_bairro([
        obs("a", 6000, "Aldeota"), obs("b", 7000, "aldeóta"), obs("c", 8000, "ALDEOTA "),
        obs("d", 9000, "Aldeota"),
    ])
    (aldeota,) = r["bairros"]
    # Exibe a grafia mais frequente, não a primeira que apareceu.
    assert aldeota["bairro"] == "Aldeota"
    assert aldeota["serie"][0]["n"] == 4
    # Pedido sem acento/caixa encontra o mesmo bairro.
    assert serie_por_bairro([obs("a", 6000, "Aldeóta")], ["aldeota"])["bairros"][0]["total"] == 1


def test_sem_bairros_pedidos_usa_os_de_maior_volume():
    dados = [obs(f"m{i}", 7000, "Meireles") for i in range(5)]
    dados += [obs(f"a{i}", 7000, "Aldeota") for i in range(3)]
    dados += [obs("c0", 7000, "Cocó"), obs("s0", 7000, None), obs("s1", 7000, "  ")]
    r = serie_por_bairro(dados, limite=2)
    assert [b["bairro"] for b in r["bairros"]] == ["Meireles", "Aldeota"]
    # O seletor recebe todos, também por volume; sem bairro fica fora.
    assert [(d["bairro"], d["total"]) for d in r["disponiveis"]] == [("Meireles", 5), ("Aldeota", 3), ("Cocó", 1)]


def test_bairro_pedido_sem_historico_volta_com_serie_vazia():
    r = serie_por_bairro([obs("a", 7000, "Meireles")], ["Meireles", "Praia de Iracema"])
    assert [(b["bairro"], b["total"], b["serie"]) for b in r["bairros"]][1] == ("Praia de Iracema", 0, [])


def test_volume_conta_anuncios_distintos_nao_pontos():
    # Anúncio parado no ar 3 semanas não vale mais que 2 anúncios distintos.
    dados = [obs("x", 7000, "Cocó", semana=s) for s in ("2026-W35", "2026-W36", "2026-W37")]
    dados += [obs("a", 7000, "Aldeota"), obs("b", 7000, "Aldeota")]
    assert [b["bairro"] for b in serie_por_bairro(dados)["bairros"]] == ["Aldeota", "Cocó"]


def test_ler_lista_bairros_aceita_virgula_e_repeticao():
    assert ler_lista_bairros(["Aldeota, Meireles", "Cocó", "aldeota", ""]) == ["Aldeota", "Meireles", "Cocó"]
    assert ler_lista_bairros(None) == []


# ── F6.3: endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def api(tmp_path):
    """App real com o banco trocado por um SQLite em arquivo temporário.

    Arquivo em vez de :memory: porque o TestClient roda as rotas em outro event
    loop; NullPool evita reaproveitar conexão aiosqlite entre loops."""
    import main
    from services.auth import gerar_token

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'teste.db'}", poolclass=NullPool)
    sessao = async_sessionmaker(engine, expire_on_commit=False)

    async def preparar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessao() as db:
            await gravar(db, [
                emp("https://vr/1", 7000, bairro="Meireles"),
                emp("https://vr/2", 8000, bairro="Meireles"),
                emp("https://vr/3", 9000, bairro="Meireles"),
                emp("https://vr/4", 6000, bairro="Aldeota"),
                emp("https://vr/5", 5000, bairro="Aldeota", quartos=3),
            ])
            await gravar(db, [
                emp("https://vr/1", 7300, bairro="Meireles", quando=SEMANA_2),
                emp("https://vr/4", 6100, bairro="aldeota", quando=SEMANA_2),
            ], quando=SEMANA_2, preco_max=800_000)
    asyncio.run(preparar())

    async def db_de_teste():
        async with sessao() as db:
            yield db

    main.app.dependency_overrides[get_db] = db_de_teste
    try:
        yield TestClient(main.app), {"Authorization": f"Bearer {gerar_token()}"}
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())


def test_endpoint_evolucao_bairros(api):
    cliente, auth = api
    resp = cliente.get("/api/historico/evolucao-bairros", params={"cidade": "Fortaleza, CE"}, headers=auth)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["cidade"] == "Fortaleza, CE" and corpo["quartos"] is None
    assert corpo["min_amostra"] == 3
    assert corpo["periodos"] == ["2026-W36", "2026-W37"]
    assert [b["bairro"] for b in corpo["bairros"]] == ["Meireles", "Aldeota"]
    meireles = corpo["bairros"][0]
    assert meireles["serie"][0] == {"semana": "2026-W36", "preco_m2_medio": 8000.0,
                                    "preco_m2_mediana": 8000.0, "n": 3, "pouco_confiavel": False}
    assert meireles["serie"][1]["pouco_confiavel"] is True


def test_endpoint_filtra_bairros_e_quartos(api):
    cliente, auth = api
    resp = cliente.get("/api/historico/evolucao-bairros",
                       params={"cidade": "Fortaleza, CE", "quartos": 2, "bairros": "aldeóta"}, headers=auth)
    corpo = resp.json()
    (aldeota,) = corpo["bairros"]
    assert aldeota["bairro"] == "Aldeota"
    # O anúncio de 3 quartos ficou fora.
    assert [p["preco_m2_medio"] for p in aldeota["serie"]] == [6000.0, 6100.0]
    # Parâmetro repetido também vale.
    resp = cliente.get("/api/historico/evolucao-bairros?cidade=Fortaleza,%20CE&bairros=Meireles&bairros=Aldeota",
                       headers=auth)
    assert [b["bairro"] for b in resp.json()["bairros"]] == ["Meireles", "Aldeota"]


def test_endpoint_evolucao_cidade_passa_a_ter_dados(api):
    cliente, auth = api
    resp = cliente.get("/api/historico/evolucao", params={"cidade": "Fortaleza, CE"}, headers=auth)
    assert resp.json() == {"cidade": "Fortaleza, CE", "serie": [
        {"semana": "2026-W36", "preco_m2_medio": 7000.0, "total": 5, "pouco_confiavel": False},
        {"semana": "2026-W37", "preco_m2_medio": 6700.0, "total": 2, "pouco_confiavel": True},
    ]}


def test_endpoint_exige_login(api):
    cliente, _ = api
    assert cliente.get("/api/historico/evolucao-bairros", params={"cidade": "Fortaleza, CE"}).status_code == 401
