"""Dossiê do empreendimento e busca por nome/endereço (services/dossie.py).

Banco em memória com buscas gravadas como o pipeline grava; geocodificação
trocada por uma falsa — nenhum teste vai à rede.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from database import models_db  # noqa: E402,F401
from database.connection import Base, get_db  # noqa: E402
from database.models_db import BuscaSalva  # noqa: E402
from models import BuscaRequest, BuscaResponse, Empreendimento  # noqa: E402
from repositories.busca_repo import salvar_busca  # noqa: E402
from repositories.empreendimento_repo import historico_da_cidade  # noqa: E402
from services import dossie, geocoding  # noqa: E402
from services.search import aplicar_agrupamento  # noqa: E402

SEMANA_1 = datetime(2026, 9, 7, 10, 0)
SEMANA_2 = datetime(2026, 9, 14, 10, 0)


def emp(url, preco, area=60, *, nome_anuncio='Apto', nome=None, bairro='Cocó', endereco=None,
        lat=None, lng=None, portal='vivareal', quando=SEMANA_1):
    return Empreendimento(
        id=url, nome_anuncio=nome_anuncio, nome_empreendimento=nome, construtora=None,
        cidade='fortaleza', bairro=bairro, endereco=endereco, portal=portal,
        latitude=lat, longitude=lng, origem_coordenada='exata' if lat is not None else None,
        preco=preco, area_m2=area, preco_m2=round(preco / area, 2), quartos=2, banheiros=1,
        vagas=1, descricao=None, url_anuncio=url, data_coleta=quando,
    )


async def gravar(db, emps, quando=SEMANA_1):
    resp = aplicar_agrupamento(BuscaResponse(
        total=len(emps), preco_m2_medio=1, preco_m2_min=1, preco_m2_max=1,
        empreendimentos=emps, tempo_coleta_segundos=0,
    ))
    req = BuscaRequest(cidade='Fortaleza, CE', preco_min=1, preco_max=9_000_000)
    busca_id = await salvar_busca(db, req, resp)
    await db.execute(update(BuscaSalva).where(BuscaSalva.id == busca_id).values(criado_em=quando))
    await db.commit()
    return resp


def com_banco(corpo):
    async def rodar():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await corpo(db)
        finally:
            await engine.dispose()
    return asyncio.run(rodar())


PREDIO = dict(lat=-3.7461, lng=-38.4710, endereco='Rua Vilebaldo Aguiar')


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    async def geo_falso(endereco, cidade):
        if '1000' in (endereco or ''):
            return {'latitude': -3.7461, 'longitude': -38.4710, 'rua': 'Rua Vilebaldo Aguiar',
                    'numero': '1000', 'bairro': 'Cocó', 'precisa': True, 'descricao': 'OSM'}
        return None
    monkeypatch.setattr(geocoding, 'geocodificar', geo_falso)


def test_historico_uma_vez_por_anuncio_com_primeira_e_ultima_vez():
    async def corpo(db):
        await gravar(db, [emp('u1', 600_000, **PREDIO)], quando=SEMANA_1)
        await gravar(db, [emp('u1', 580_000, quando=SEMANA_2, **PREDIO)], quando=SEMANA_2)
        return await historico_da_cidade(db, 'Fortaleza, CE')
    hist = com_banco(corpo)
    assert len(hist) == 1
    assert hist[0]['preco'] == 580_000            # observação mais recente
    assert hist[0]['primeira_vez'] == SEMANA_1
    assert hist[0]['ultima_vez'] == SEMANA_2


def test_dossie_pelo_id_da_busca():
    async def corpo(db):
        resp = await gravar(db, [
            emp('u1', 600_000, **PREDIO), emp('u2', 640_000, 64, **PREDIO),
            emp('u3', 300_000, bairro='Centro'),
        ])
        gid = resp.grupos[0].grupo_id
        return gid, await dossie.montar_dossie(db, 'Fortaleza, CE', gid)
    gid, d = com_banco(corpo)
    assert d['grupo']['n_anuncios'] == 2
    assert {a['url_anuncio'] for a in d['anuncios']} == {'u1', 'u2'}
    assert d['serie'] and d['serie'][0]['n'] == 2


def test_dossie_inexistente():
    async def corpo(db):
        await gravar(db, [emp('u1', 600_000)])
        return await dossie.montar_dossie(db, 'Fortaleza, CE', 'emp_naoexiste')
    assert com_banco(corpo) is None


def test_procura_por_endereco_com_numero_usa_a_coordenada():
    async def corpo(db):
        await gravar(db, [
            emp('u1', 600_000, **PREDIO), emp('u2', 640_000, 64, **PREDIO),
            emp('longe', 600_000, lat=-3.76, lng=-38.47, endereco='Rua Vilebaldo Aguiar'),
        ])
        return await dossie.procurar_empreendimento(db, 'Fortaleza, CE', None, 'Rua Vilebaldo Aguiar, 1000')
    r = com_banco(corpo)
    assert {a['url_anuncio'] for a in r['anuncios']} == {'u1', 'u2'}
    assert {a['motivo'] for a in r['anuncios']} <= {'coordenada', 'mesmo_predio'}
    assert r['alvo']['geocodificacao_precisa'] is True
    # Mesma rua, longe do número: provável, não confirmado.
    assert [a['url_anuncio'] for a in r['provaveis']] == ['longe']


def test_procura_por_nome_acha_no_texto_e_confirma_no_mesmo_bairro():
    async def corpo(db):
        await gravar(db, [
            emp('o1', 270_000, 46, nome='Condomínio Reserva Arvoredo', bairro='Barroso', portal='olx'),
            emp('o2', 280_000, 46, nome='Residencial Reserva Arvoredo', bairro='Barroso', portal='olx'),
            # Sem prefixo: a extração não acha o nome, só o texto do título.
            emp('o3', 290_000, 50, nome_anuncio='Apto na Reserva Arvoredo, 2 quartos', bairro='Barroso', portal='olx'),
            emp('o4', 290_000, 50, nome_anuncio='Apto na Reserva Arvoredo', bairro='Aldeota', portal='olx'),
        ])
        return await dossie.procurar_empreendimento(db, 'Fortaleza, CE', 'Reserva Arvoredo', None)
    r = com_banco(corpo)
    assert {a['url_anuncio'] for a in r['anuncios']} == {'o1', 'o2', 'o3'}
    assert [a['url_anuncio'] for a in r['provaveis']] == ['o4']


def test_rua_sem_numero_sugere_os_predios_da_rua():
    async def corpo(db):
        await gravar(db, [emp('u1', 600_000, **PREDIO), emp('u2', 640_000, 64, **PREDIO)])
        return await dossie.procurar_empreendimento(db, 'Fortaleza, CE', None, 'Rua Vilebaldo Aguiar')
    r = com_banco(corpo)
    assert r['anuncios'] == []
    assert len(r['sugestoes']) == 1 and r['sugestoes'][0]['n_anuncios'] == 2


def test_variacao_vs_grupo():
    async def corpo(db):
        await gravar(db, [emp('u1', 600_000, **PREDIO), emp('u2', 720_000, **PREDIO)])
        return await dossie.procurar_empreendimento(db, 'Fortaleza, CE', None, 'Rua Vilebaldo Aguiar, 1000')
    r = com_banco(corpo)
    var = {a['url_anuncio']: a['variacao_vs_grupo_pct'] for a in r['anuncios']}
    assert var['u1'] == pytest.approx(-9.1, abs=0.1)
    assert var['u2'] == pytest.approx(9.1, abs=0.1)


# ── Endpoints ────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente():
    import main
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    fabrica = async_sessionmaker(engine, expire_on_commit=False)

    async def preparar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with fabrica() as db:
            await gravar(db, [emp('u1', 600_000, **PREDIO), emp('u2', 640_000, 64, **PREDIO)])
    asyncio.run(preparar())

    async def db_teste():
        async with fabrica() as db:
            yield db
    main.app.dependency_overrides[get_db] = db_teste
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_endpoint_procurar_exige_nome_ou_endereco(cliente):
    r = cliente.post('/api/empreendimentos/buscar', json={'cidade': 'Fortaleza, CE'})
    assert r.status_code == 422


def test_endpoint_procurar(cliente):
    r = cliente.post('/api/empreendimentos/buscar',
                     json={'cidade': 'Fortaleza, CE', 'endereco': 'Rua Vilebaldo Aguiar, 1000'})
    assert r.status_code == 200
    assert r.json()['grupo']['n_anuncios'] == 2


def test_endpoint_dossie_404(cliente):
    r = cliente.get('/api/empreendimentos/emp_x', params={'cidade': 'Fortaleza, CE'})
    assert r.status_code == 404
