"""Testes de cobertura de cidades.

A aplicação nasceu focada em Fortaleza e dois scrapers montavam a URL de forma
que só funcionava para capitais — devolvendo dados de OUTRA cidade sem erro
nenhum, que é o pior modo de falha possível para uma ferramenta de
precificação.

Os casos abaixo vêm de URLs verificadas ao vivo em 29/07/2026.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.chavesnamao import _build_url as chaves_url  # noqa: E402
from scraper.vivareal import _extrair_estado_cidade, build_vivareal_url  # noqa: E402


# ── ChavesNaMão: o bug do mapa estado → capital ──────────────────────────────

@pytest.mark.parametrize("cidade,estado,esperado", [
    ("fortaleza", "ce", "ce-fortaleza"),
    ("caucaia", "ce", "ce-caucaia"),        # antes virava ce-fortaleza
    ("sobral", "ce", "ce-sobral"),          # antes virava ce-fortaleza
    ("campinas", "sp", "sp-campinas"),      # antes virava sp-sao-paulo
    ("joinville", "sc", "sc-joinville"),
])
def test_chavesnamao_usa_a_cidade_pedida(cidade, estado, esperado):
    """Havia um mapa ESTADO → CAPITAL: buscar Caucaia devolvia Fortaleza."""
    assert f"/apartamentos-a-venda/{esperado}/" in chaves_url(cidade, estado, 280_000, 500_000, None, 1)


def test_chavesnamao_remove_acento_da_cidade():
    url = chaves_url("Goiânia", "GO", 280_000, 500_000, None, 1)
    assert "/go-goiania/" in url


def test_chavesnamao_cidade_composta():
    url = chaves_url("Belo Horizonte", "mg", 280_000, 500_000, None, 1)
    assert "/mg-belo-horizonte/" in url


# ── VivaReal: acento e a exceção de São Paulo ────────────────────────────────

@pytest.mark.parametrize("entrada,esperado", [
    ("Fortaleza, CE", ("ceara", "fortaleza")),
    ("Goiânia, GO", ("goias", "goiania")),          # acento quebrava: 404
    ("Uberlândia, MG", ("minas-gerais", "uberlandia")),
    ("Brasília, DF", ("distrito-federal", "brasilia")),
    ("Belo Horizonte, MG", ("minas-gerais", "belo-horizonte")),
])
def test_vivareal_normaliza_cidade_e_estado(entrada, esperado):
    assert _extrair_estado_cidade(entrada) == esperado


@pytest.mark.parametrize("entrada", ["São Paulo, SP", "Campinas, SP", "Santos, SP"])
def test_vivareal_usa_sigla_para_sao_paulo(entrada):
    """
    SP é a única exceção medida: `/venda/sao-paulo/campinas/` devolve 404 e
    `/venda/sp/campinas/` funciona. Provável colisão entre o nome do estado e
    o da capital.
    """
    estado, _ = _extrair_estado_cidade(entrada)
    assert estado == "sp"


def test_vivareal_monta_path_com_cidade_correta():
    estado, cidade = _extrair_estado_cidade("Campinas, SP")
    url = build_vivareal_url(cidade, estado, 280_000, 500_000, None, None, 1)
    assert "/venda/sp/campinas/" in url


# ── Validação da entrada ─────────────────────────────────────────────────────

from models import BuscaRequest  # noqa: E402


@pytest.mark.parametrize("cidade", ["Fortaleza, CE", "Campinas, SP", "Belo Horizonte, MG", "Goiânia, go"])
def test_aceita_cidade_com_uf(cidade):
    assert BuscaRequest(cidade=cidade, preco_min=280_000, preco_max=500_000).cidade == cidade


@pytest.mark.parametrize("cidade", ["Fortaleza", "Sobral", "", "Fortaleza, XX", "Fortaleza, Ceará"])
def test_rejeita_cidade_sem_uf_valida(cidade):
    """
    Sem UF o código assumia SP: buscar "Fortaleza" devolvia Fortaleza/SP.
    Falhar na cara do usuário é melhor que entregar a praça errada.
    """
    with pytest.raises(ValueError):
        BuscaRequest(cidade=cidade, preco_min=280_000, preco_max=500_000)
