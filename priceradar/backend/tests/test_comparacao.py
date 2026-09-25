"""Histórico por anúncio e alertas: comparação com a última busca igual."""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import models_db  # noqa: E402,F401
from database.connection import Base  # noqa: E402
from models import BuscaRequest, BuscaResponse, Empreendimento  # noqa: E402
from repositories.busca_repo import buscar_anterior, salvar_busca  # noqa: E402
from services.comparacao import comparar_com_anterior  # noqa: E402


def req(**kw):
    base = {"cidade": "Fortaleza, CE", "preco_min": 280_000, "preco_max": 500_000, "quartos": 2}
    base.update(kw)
    return BuscaRequest(**base)


def emp(url, preco, portal="vivareal"):
    return Empreendimento(
        id=url, nome_anuncio="Apto", nome_empreendimento=None, construtora=None, cidade="fortaleza",
        bairro="Meireles", portal=portal, preco=preco, area_m2=60, preco_m2=preco / 60, quartos=2,
        banheiros=1, vagas=1, descricao=None, url_anuncio=url, data_coleta=datetime.now(),
    )


def resposta(emps):
    return BuscaResponse(total=len(emps), preco_m2_medio=7000, preco_m2_min=6000, preco_m2_max=8000,
                         empreendimentos=emps, tempo_coleta_segundos=1)


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


def test_primeira_busca_nao_tem_comparacao_nem_selo():
    async def corpo(db):
        r = resposta([emp("https://vr/1", 400_000)])
        comparar_com_anterior(r, await buscar_anterior(db, req()))
        assert r.comparacao is None
        assert not r.empreendimentos[0].novo
    com_banco(corpo)


def test_segunda_busca_marca_novo_preco_e_saidas():
    async def corpo(db):
        await salvar_busca(db, req(), resposta([
            emp("https://vr/1", 400_000),                 # vai baixar
            emp("https://vr/2/?utm=x", 300_000),          # igual (URL com query/barra)
            emp("https://vr/3", 350_000),                 # sai do ar (portal respondeu)
            emp("https://ol/9", 320_000, portal="olx"),   # portal não respondeu desta vez
            emp("https://vr/5", 390_000),                 # variação de arredondamento
        ]))
        atual = resposta([
            emp("https://vr/1", 380_000),
            emp("https://vr/2", 300_000),
            emp("https://vr/4", 410_000),                 # novo
            emp("https://vr/5", 390_900),                 # +0,23%: não conta
        ])
        comparar_com_anterior(atual, await buscar_anterior(db, req()))
        c = atual.comparacao
        assert (c.novos, c.baixaram, c.subiram, c.sairam) == (1, 1, 0, 1)
        porurl = {e.url_anuncio: e for e in atual.empreendimentos}
        assert porurl["https://vr/1"].preco_anterior == 400_000
        assert porurl["https://vr/4"].novo
        assert porurl["https://vr/2"].preco_anterior is None and not porurl["https://vr/2"].novo
        assert porurl["https://vr/5"].preco_anterior is None
    com_banco(corpo)


def test_so_compara_com_busca_igual():
    async def corpo(db):
        await salvar_busca(db, req(quartos=3), resposta([emp("https://vr/1", 400_000)]))
        assert await buscar_anterior(db, req(quartos=2)) is None
    com_banco(corpo)


def test_cache_compara_com_a_anterior_ao_cache():
    async def corpo(db):
        await salvar_busca(db, req(), resposta([emp("https://vr/1", 400_000)]))
        await asyncio.sleep(0.01)
        await salvar_busca(db, req(), resposta([emp("https://vr/1", 380_000)]))   # esta é o "cache"
        anterior = await buscar_anterior(db, req(), pular=1)
        assert anterior.empreendimentos[0].preco == 400_000
    com_banco(corpo)
