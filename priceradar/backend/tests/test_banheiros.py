"""Testes do filtro de banheiros e da chave do cache de buscas.

O filtro segue a regra de quartos: só descarta quando o anúncio declara
banheiros e diverge — anúncio sem a informação continua. O valor 4 significa
"4 ou mais".

O cache ganhou `banheiros` e `tipo_edificacao` na chave. `tipo_edificacao`
faltava antes: uma busca "só torre" feita logo depois de uma busca sem filtro
saía do cache sem filtro nenhum.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import models_db  # noqa: E402,F401 — registra as tabelas no Base
from database.connection import Base  # noqa: E402
from models import BuscaRequest, BuscaResponse, Empreendimento  # noqa: E402
from repositories.busca_repo import buscar_cache_recente, salvar_busca  # noqa: E402
from services.validacao import filtrar_anuncios, validar_anuncio  # noqa: E402


def req(**kw):
    base = {"cidade": "Fortaleza, CE", "preco_min": 280_000, "preco_max": 500_000}
    base.update(kw)
    return BuscaRequest(**base)


def anuncio(**kw):
    base = {
        "nome_anuncio": "Apartamento à venda com 2 quartos",
        "descricao": "Apartamento bem localizado",
        "url_anuncio": "https://exemplo.com/imovel/1",
        "preco": 400_000.0,
        "area_m2": 60.0,
        "preco_m2": 6_666.67,
        "quartos": 2,
        "banheiros": 2,
        "cidade": "fortaleza",
    }
    base.update(kw)
    return base


# ── Filtro ───────────────────────────────────────────────────────────────────

def test_sem_filtro_aceita_qualquer_quantidade():
    for n in (1, 2, 5):
        assert validar_anuncio(anuncio(banheiros=n), req()) == (True, None)


def test_exato_aceita_igual_e_descarta_diferente():
    assert validar_anuncio(anuncio(banheiros=2), req(banheiros=2)) == (True, None)
    assert validar_anuncio(anuncio(banheiros=1), req(banheiros=2)) == (False, 'banheiros_divergente')
    assert validar_anuncio(anuncio(banheiros=3), req(banheiros=2)) == (False, 'banheiros_divergente')


def test_quatro_significa_quatro_ou_mais():
    assert validar_anuncio(anuncio(banheiros=4), req(banheiros=4)) == (True, None)
    assert validar_anuncio(anuncio(banheiros=6), req(banheiros=4)) == (True, None)
    assert validar_anuncio(anuncio(banheiros=3), req(banheiros=4)) == (False, 'banheiros_divergente')


def test_anuncio_sem_banheiros_nao_e_descartado():
    assert validar_anuncio(anuncio(banheiros=None), req(banheiros=2)) == (True, None)


def test_banheiros_como_string_do_portal():
    assert validar_anuncio(anuncio(banheiros="2"), req(banheiros=2)) == (True, None)
    assert validar_anuncio(anuncio(banheiros="3"), req(banheiros=2)) == (False, 'banheiros_divergente')


def test_diagnostico_conta_o_descarte():
    itens = [anuncio(banheiros=2), anuncio(banheiros=1), anuncio(banheiros=3), anuncio(banheiros=None)]
    validos, descartes = filtrar_anuncios(itens, req(banheiros=2))
    assert len(validos) == 2
    assert descartes == {'banheiros_divergente': 2}


def test_request_normaliza_valores():
    assert req(banheiros=0).banheiros is None   # "Todos" de cliente antigo
    assert req(banheiros=7).banheiros == 4      # acima do teto vira "4 ou mais"
    with pytest.raises(ValidationError):
        req(banheiros=-1)


# ── Cache ────────────────────────────────────────────────────────────────────

def _resposta(fotos=None) -> BuscaResponse:
    emp = Empreendimento(
        id="x", nome_anuncio="Apto", nome_empreendimento=None, construtora=None,
        cidade="fortaleza", bairro="Meireles", portal="vivareal",
        preco=400_000, area_m2=60, preco_m2=6_666.67,
        quartos=2, banheiros=2, vagas=1, descricao=None,
        url_anuncio="https://exemplo.com/1", data_coleta=datetime.now(),
        fotos=fotos or [],
    )
    return BuscaResponse(
        total=1, preco_m2_medio=6_666.67, preco_m2_min=6_666.67, preco_m2_max=6_666.67,
        empreendimentos=[emp], tempo_coleta_segundos=1.0,
    )


def _com_banco(corpo):
    async def rodar():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessao = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessao() as db:
                return await corpo(db)
        finally:
            await engine.dispose()
    return asyncio.run(rodar())


def test_cache_nao_mistura_banheiros_diferentes():
    async def corpo(db):
        await salvar_busca(db, req(banheiros=2), _resposta())
        assert await buscar_cache_recente(db, req(banheiros=2), 60) is not None
        assert await buscar_cache_recente(db, req(banheiros=3), 60) is None
        assert await buscar_cache_recente(db, req(), 60) is None
    _com_banco(corpo)


def test_cache_nao_mistura_tipo_edificacao():
    async def corpo(db):
        await salvar_busca(db, req(), _resposta())
        assert await buscar_cache_recente(db, req(tipo_edificacao="torre"), 60) is None
        assert await buscar_cache_recente(db, req(), 60) is not None
    _com_banco(corpo)


def test_cache_preserva_fotos():
    fotos = ["https://img.exemplo.com/1.jpg", "https://img.exemplo.com/2.jpg"]

    async def corpo(db):
        await salvar_busca(db, req(), _resposta(fotos))
        cache = await buscar_cache_recente(db, req(), 60)
        assert cache.empreendimentos[0].fotos == fotos
    _com_banco(corpo)
