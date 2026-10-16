"""Identidade combinada: fixtures locais, limites e caso Parque Marista."""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.connection import Base  # noqa: E402
from models import BuscaRequest, BuscaResponse, Empreendimento  # noqa: E402
from repositories.busca_repo import salvar_busca  # noqa: E402
from repositories.identidade_cache_repo import gravar_cache, ler_cache  # noqa: E402
from services import catalogos_oficiais, detalhes_anuncios, dossie, geocoding  # noqa: E402
from services.catalogos_oficiais import PROVEDORES, extrair_referencia_detalhe  # noqa: E402
from services.detalhes_anuncios import extrair_detalhe, selecionar_candidatos  # noqa: E402
from services.search import aplicar_agrupamento  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "identidade"


def _emp(url, preco, *, titulo="Apartamento", nome=None, endereco=None, bairro="Benfica", portal="olx"):
    return Empreendimento(
        id=url, nome_anuncio=titulo, nome_empreendimento=nome, construtora=None,
        cidade="fortaleza", bairro=bairro, endereco=endereco, portal=portal,
        preco=preco, area_m2=50, preco_m2=preco / 50, quartos=2, banheiros=1,
        vagas=1, descricao=None, url_anuncio=url, data_coleta=datetime(2026, 10, 1),
    )


def _com_banco(corpo):
    async def executar():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await corpo(db)
        finally:
            await engine.dispose()
    return asyncio.run(executar())


async def _gravar(db, itens):
    resposta = aplicar_agrupamento(BuscaResponse(
        total=len(itens), preco_m2_medio=1, preco_m2_min=1, preco_m2_max=1,
        empreendimentos=itens, tempo_coleta_segundos=0,
    ))
    await salvar_busca(db, BuscaRequest(cidade="Fortaleza, CE", preco_min=1, preco_max=9_000_000), resposta)


@pytest.mark.parametrize("portal", ["olx", "vivareal", "zapimoveis", "imovelweb", "chavesnamao"])
def test_fixtures_dos_cinco_portais_extraem_identidade(portal):
    detalhe = extrair_detalhe((FIXTURES / f"{portal}.html").read_text(encoding="utf-8"), portal)
    assert "Parque Marista" in (detalhe["nome_empreendimento"] or detalhe["nome_anuncio"])
    assert "Conselheiro Tristão" in detalhe["endereco"]


@pytest.mark.parametrize("indice", range(4))
def test_fixtures_das_quatro_construtoras_nao_expoem_preco(indice):
    provedor = PROVEDORES[indice]
    html = (FIXTURES / f"{provedor.nome}.html").read_text(encoding="utf-8")
    ref = extrair_referencia_detalhe(html, provedor=provedor, url="https://oficial/item",
                                    nome_listagem="Parque Marista", cidade="Fortaleza, CE")
    assert ref["nome"] == "Parque Marista"
    assert ref["endereco"].endswith("60")
    assert "preco" not in ref and "preço" not in ref


def test_limite_de_detalhes_e_quatro_por_portal():
    itens = []
    for portal in ("olx", "vivareal", "zap", "imovelweb", "chavesnamao"):
        for n in range(8):
            itens.append({"portal": portal, "url_anuncio": f"https://{portal}.test/{n}"})
    escolhidos = selecionar_candidatos(itens)
    assert len(escolhidos) == 12
    assert max(sum(i["portal"] == p for i in escolhidos) for p in {i["portal"] for i in escolhidos}) <= 4


def test_parque_marista_combina_nome_e_endereco(monkeypatch):
    referencia = {
        "nome": "Parque Marista", "aliases": [], "construtora": "MRV",
        "endereco": "Rua Conselheiro Tristão, 60", "bairro": "Benfica",
        "cidade": "Fortaleza", "fonte": "mrv", "url": "https://mrv.test/parque-marista",
    }
    async def ref_falsa(db, cidade, nome, diagnostico):
        return referencia
    async def sem_detalhes(db, itens, diagnostico):
        return itens
    async def sem_geo(endereco, cidade):
        return None
    monkeypatch.setattr(catalogos_oficiais, "buscar_referencia_oficial", ref_falsa)
    monkeypatch.setattr(detalhes_anuncios, "enriquecer_candidatos", sem_detalhes)
    monkeypatch.setattr(geocoding, "geocodificar", sem_geo)

    async def corpo(db):
        await _gravar(db, [
            _emp("nome", 260_000, titulo="Apartamento no Parque Marista"),
            _emp("endereco", 280_000, endereco="Rua Conselheiro Tristão, 60", portal="vivareal"),
            _emp("numero-errado", 999_000, endereco="Rua Conselheiro Tristão, 600", portal="zap"),
            _emp("outro-bairro", 888_000, titulo="Parque Marista", bairro="Aldeota"),
        ])
        return await dossie.procurar_empreendimento(
            db, "Fortaleza, CE", "Parque Marista", "Rua Conselheiro Tristão, 60",
            bairro="Benfica", aprofundar=True,
        )
    resposta = _com_banco(corpo)
    confirmados = {a["url_anuncio"]: a for a in resposta["anuncios"]}
    assert set(confirmados) == {"nome", "endereco"}
    assert confirmados["endereco"]["classe_vinculo"] == "direto"
    assert confirmados["nome"]["classe_vinculo"] == "corroborado"
    assert resposta["grupo"]["preco_m2_mediana"] == pytest.approx(5_400)
    assert {a["url_anuncio"] for a in resposta["provaveis"]} == {"numero-errado", "outro-bairro"}
    assert resposta["resumo_vinculos"] == {"direto": 1, "corroborado": 1, "provavel": 2,
                                            "participam_mediana": 2}


def test_nome_e_rua_sem_numero_sao_corroborados_pela_referencia(monkeypatch):
    referencia = {
        "nome": "Parque Marista", "aliases": [], "construtora": "MRV",
        "endereco": "Rua Conselheiro Tristão, 60", "bairro": "Benfica",
        "cidade": "Fortaleza", "fonte": "mrv", "url": "https://mrv.test/parque-marista",
    }
    async def ref_falsa(db, cidade, nome, diagnostico):
        return referencia
    async def sem_detalhes(db, itens, diagnostico):
        return itens
    async def sem_geo(endereco, cidade):
        return None
    monkeypatch.setattr(catalogos_oficiais, "buscar_referencia_oficial", ref_falsa)
    monkeypatch.setattr(detalhes_anuncios, "enriquecer_candidatos", sem_detalhes)
    monkeypatch.setattr(geocoding, "geocodificar", sem_geo)

    async def corpo(db):
        await _gravar(db, [
            _emp("so-nome", 260_000, titulo="Parque Marista", bairro=None),
            _emp("so-rua", 280_000, endereco="Rua Conselheiro Tristão", bairro=None, portal="vivareal"),
        ])
        return await dossie.procurar_empreendimento(
            db, "Fortaleza, CE", "Parque Marista", "Rua Conselheiro Tristão", aprofundar=True,
        )
    resposta = _com_banco(corpo)
    assert {a["url_anuncio"] for a in resposta["anuncios"]} == {"so-nome", "so-rua"}
    assert {a["classe_vinculo"] for a in resposta["anuncios"]} == {"corroborado"}


def test_conflito_com_catalogo_preserva_endereco_informado_e_nao_promove(monkeypatch):
    referencia = {
        "nome": "Parque Marista", "aliases": [], "construtora": "MRV",
        "endereco": "Rua Oficial, 60", "bairro": "Benfica", "cidade": "Fortaleza",
        "fonte": "mrv", "url": "https://mrv.test/parque-marista",
    }
    async def ref_falsa(db, cidade, nome, diagnostico):
        return referencia
    async def sem_detalhes(db, itens, diagnostico):
        return itens
    async def sem_geo(endereco, cidade):
        return None
    monkeypatch.setattr(catalogos_oficiais, "buscar_referencia_oficial", ref_falsa)
    monkeypatch.setattr(detalhes_anuncios, "enriquecer_candidatos", sem_detalhes)
    monkeypatch.setattr(geocoding, "geocodificar", sem_geo)

    async def corpo(db):
        await _gravar(db, [_emp("nome", 260_000, titulo="Parque Marista", bairro=None)])
        return await dossie.procurar_empreendimento(
            db, "Fortaleza, CE", "Parque Marista", "Rua Informada, 10", aprofundar=True,
        )
    resposta = _com_banco(corpo)
    assert resposta["alvo"]["endereco"] == "Rua Informada, 10"
    assert "ruas diferentes" in resposta["alvo"]["conflito_referencia_oficial"]
    assert resposta["anuncios"] == []
    assert resposta["provaveis"][0]["classe_vinculo"] == "provavel"


def test_cache_de_identidade_reutiliza_payload():
    async def corpo(db):
        from datetime import timedelta
        await gravar_cache(db, "anuncio_detalhe", "u", "olx", "https://u", {"nome": "X"}, timedelta(days=30))
        return await ler_cache(db, "anuncio_detalhe", "u")
    assert _com_banco(corpo)["payload"] == {"nome": "X"}

