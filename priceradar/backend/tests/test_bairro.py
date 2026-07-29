"""Testes da extração e do filtro de bairro.

Contexto: o JSON-LD de VivaReal e Zap não traz bairro — `addressLocality` é a
CIDADE e `streetAddress` é o logradouro. O scraper gravava o logradouro no
campo `bairro`, e por isso filtrar por "Aldeota" comparava o texto com um nome
de rua e devolvia quase nada.

O bairro só existe no slug da URL do anúncio. Os casos abaixo são URLs reais
capturadas em 29/07/2026.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.parser import extrair_bairro_do_slug  # noqa: E402
from scraper.vivareal import build_vivareal_url  # noqa: E402
from scraper.zapimoveis import build_zapimoveis_url  # noqa: E402


@pytest.mark.parametrize("url,cidade,esperado", [
    # VivaReal: bairro antes da cidade, seguido de descritores
    ("https://www.vivareal.com.br/imovel/apartamento-3-quartos-jose-bonifacio-fortaleza-com-garagem-78m2-venda-RS590000-id-2586178388/",
     "Fortaleza", "Jose Bonifacio"),
    # Bairro com três tokens
    ("https://www.vivareal.com.br/imovel/apartamento-2-quartos-manuel-dias-branco-fortaleza-com-garagem-50m2-venda-RS300000-id-1/",
     "Fortaleza", "Manuel Dias Branco"),
    # Zap: descritores de amenidade antes do bairro
    ("https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-area-de-servico-montese-fortaleza-ce-86m2-id-2/",
     "Fortaleza", "Montese"),
    # Cidade com dois tokens
    ("https://www.vivareal.com.br/imovel/apartamento-2-quartos-moema-sao-paulo-com-garagem-60m2-venda-RS900000-id-9/",
     "Sao Paulo", "Moema"),
])
def test_extrai_bairro_do_slug(url, cidade, esperado):
    assert extrair_bairro_do_slug(url, cidade) == esperado


def test_amenidade_nao_vaza_para_o_bairro():
    """Sem a stopword 'cozinha' o resultado virava 'Cozinha Jangurussu'."""
    url = "https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-cozinha-jangurussu-fortaleza-57m2-id-3/"
    assert extrair_bairro_do_slug(url, "Fortaleza") == "Jangurussu"


@pytest.mark.parametrize("url,cidade", [
    # Lançamento: slug em outro formato, sem bairro. Melhor vazio que errado.
    ("https://www.vivareal.com.br/imoveis-lancamentos/vitoria-iris-id-2873135582/", "Fortaleza"),
    # Cidade ausente do slug — sem âncora, sem extração
    ("https://www.vivareal.com.br/imovel/apartamento-2-quartos-id-7/", "Fortaleza"),
    ("", "Fortaleza"),
    ("https://exemplo.com/x/", ""),
])
def test_sem_evidencia_devolve_none(url, cidade):
    assert extrair_bairro_do_slug(url, cidade) is None


def test_acento_na_cidade_nao_impede_ancoragem():
    url = "https://www.vivareal.com.br/imovel/apartamento-2-quartos-centro-goiania-com-garagem-60m2-venda-RS400000-id-5/"
    assert extrair_bairro_do_slug(url, "Goiânia") == "Centro"


# ── Filtro na origem ─────────────────────────────────────────────────────────

def test_vivareal_filtra_bairro_no_path():
    """`&bairros=` é ignorado pelo site; `/bairros/{slug}/` filtra de verdade."""
    url = build_vivareal_url("fortaleza", "ceara", 280_000, 500_000, None, "Aldeota")
    assert "/bairros/aldeota/" in url
    assert "&bairros=" not in url


def test_vivareal_normaliza_acento_do_bairro():
    url = build_vivareal_url("fortaleza", "ceara", 280_000, 500_000, None, "Fátima")
    assert "/bairros/fatima/" in url


def test_vivareal_sem_bairro_mantem_url_original():
    url = build_vivareal_url("fortaleza", "ceara", 280_000, 500_000, None, None)
    assert "/fortaleza/apartamento_residencial/" in url
    assert "bairros" not in url


def test_zap_nao_coloca_bairro_na_url():
    """O Zap ignora bairro em path e query — o filtro dele é em memória."""
    url = build_zapimoveis_url("fortaleza", "ce", 280_000, 500_000, None, "Aldeota")
    assert "aldeota" not in url.lower()
