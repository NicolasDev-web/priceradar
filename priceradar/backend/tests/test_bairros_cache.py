"""Testes da união de bairros e do cache em disco.

`_unir` prometia ficar com a grafia acentuada entre "Cocó" (payload) e "Coco"
(slug da URL), e a condição nunca disparava: comparava com `_normalizar`, que
também baixa a caixa, então `_normalizar("Coco") == "coco" != "Coco"` e todo
nome em Title Case passava por acentuado. Em `listar_bairros` o defeito era
invisível — o payload entra primeiro. Em `registrar_bairros_vistos`, que lê o
disco primeiro, "Coco" venceria "Cocó" para sempre.

O cache agora é escrito a cada busca, e não mais só na varredura: por isso os
testes de atomicidade e de acúmulo.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import bairros  # noqa: E402
from services.bairros import (  # noqa: E402
    _slug_para_nome,
    _tem_acento,
    _unir,
    registrar_bairros_vistos,
)


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    """`_cache` e `_CACHE_PATH` são globais de módulo e vazariam entre testes.

    `_CACHE_PATH` é resolvido no import a partir da env var, então tem que ser
    substituído no atributo do módulo — mexer em `os.environ` não teria efeito.
    """
    monkeypatch.setattr(bairros, "_CACHE_PATH", tmp_path / "bairros_por_cidade.json")
    monkeypatch.setattr(bairros, "_cache", {})
    yield


def ler_disco() -> dict:
    caminho = bairros._CACHE_PATH
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


# --------------------------------------------------------------------------
# _tem_acento — a guarda contra o bug voltar
# --------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Cocó", True),
    ("Aracapé", True),
    ("Passaré", True),
    ("Coco", False),
    ("Meireles", False),
    # O bug original: `_normalizar` baixa a caixa, então Title Case parecia
    # acentuado. Se alguém voltar a usá-lo aqui, estas três linhas caem.
    ("Coco", False),
    ("MEIRELES", False),
    ("Sao Joao do Tauape", False),
])
def test_tem_acento_nao_confunde_caixa_com_acento(texto, esperado):
    assert _tem_acento(texto) is esperado


# --------------------------------------------------------------------------
# _unir
# --------------------------------------------------------------------------

def test_acentuada_vence_a_sem_acento():
    assert _unir(["Coco"], ["Cocó"]) == ["Cocó"]


def test_acentuada_vence_mesmo_chegando_por_ultimo():
    """A ordem que `registrar_bairros_vistos` usa: disco primeiro, novo depois."""
    assert _unir(["Coco", "Meireles"], ["Cocó"]) == ["Cocó", "Meireles"]


def test_acentuada_vence_mesmo_chegando_primeiro():
    assert _unir(["Cocó"], ["Coco"]) == ["Cocó"]


def test_sem_acento_em_nenhuma_mantem_a_primeira():
    assert _unir(["Centro"], ["centro"]) == ["Centro"]


def test_une_sem_repetir_e_ordena():
    assert _unir(["Messejana", "Aldeota"], ["Meireles", "Aldeota"]) == [
        "Aldeota", "Meireles", "Messejana",
    ]


@pytest.mark.parametrize("nome", [
    "Área Rural de Caucaia",
    "Area Rural de Fortaleza",
    "área rural de Sobral",
])
def test_descarta_area_rural(nome):
    """Categoria residual do portal, não bairro que alguém compare a preço."""
    assert _unir([nome, "Meireles"]) == ["Meireles"]


@pytest.mark.parametrize("nome", ["", "   ", "\t"])
def test_descarta_vazio_e_so_espaco(nome):
    assert _unir([nome, "Meireles"]) == ["Meireles"]


def test_apara_espaco_nas_bordas():
    assert _unir(["  Meireles  "]) == ["Meireles"]


def test_sem_fontes_devolve_vazio():
    assert _unir() == []


# --------------------------------------------------------------------------
# _slug_para_nome
# --------------------------------------------------------------------------

@pytest.mark.parametrize("slug,esperado", [
    ("sao-joao-do-tauape", "Sao Joao do Tauape"),
    ("meireles", "Meireles"),
    ("coco", "Coco"),                      # não reacenta: o dado não está no slug
    ("praia-de-iracema", "Praia de Iracema"),
    ("dias-macedo", "Dias Macedo"),
    ("de-lourdes", "De Lourdes"),          # preposição inicial ainda capitaliza
])
def test_slug_para_nome(slug, esperado):
    assert _slug_para_nome(slug) == esperado


# --------------------------------------------------------------------------
# registrar_bairros_vistos — o cache em disco
# --------------------------------------------------------------------------

def test_registrar_cria_o_arquivo():
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles", "Cocó"])
    assert ler_disco() == {"fortaleza, ce": ["Cocó", "Meireles"]}


def test_chave_normaliza_caixa_e_espaco():
    registrar_bairros_vistos("  Fortaleza, CE  ", ["Meireles"])
    assert "fortaleza, ce" in ler_disco()


def test_registrar_acumula_entre_chamadas():
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles"])
    registrar_bairros_vistos("Fortaleza, CE", ["Messejana"])
    assert ler_disco()["fortaleza, ce"] == ["Meireles", "Messejana"]


def test_cidades_diferentes_nao_se_misturam():
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles"])
    registrar_bairros_vistos("Caucaia, CE", ["Icaraí"])
    disco = ler_disco()
    assert disco["fortaleza, ce"] == ["Meireles"]
    assert disco["caucaia, ce"] == ["Icaraí"]


@pytest.mark.parametrize("entrada", [[], [""], ["   "], [None]])
def test_registrar_sem_nome_util_nao_escreve(entrada):
    registrar_bairros_vistos("Fortaleza, CE", entrada)
    assert not bairros._CACHE_PATH.exists()


def test_grafia_acentuada_substitui_a_do_disco():
    """O bug ponta a ponta: grava "Coco", registra "Cocó", tem que ler "Cocó"."""
    registrar_bairros_vistos("Fortaleza, CE", ["Coco"])
    assert ler_disco()["fortaleza, ce"] == ["Coco"]

    registrar_bairros_vistos("Fortaleza, CE", ["Cocó"])
    assert ler_disco()["fortaleza, ce"] == ["Cocó"]


def test_grafia_sem_acento_nao_derruba_a_acentuada():
    registrar_bairros_vistos("Fortaleza, CE", ["Cocó"])
    registrar_bairros_vistos("Fortaleza, CE", ["Coco"])
    assert ler_disco()["fortaleza, ce"] == ["Cocó"]


def test_cache_em_memoria_acompanha_o_disco():
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles"])
    assert bairros._cache["fortaleza, ce"] == ["Meireles"]


def test_cache_corrompido_nao_derruba_o_registro():
    """Antes da escrita atômica, um JSON truncado apagava tudo em silêncio."""
    bairros._CACHE_PATH.write_text('{"fortaleza, ce": ["Meire', encoding="utf-8")

    registrar_bairros_vistos("Fortaleza, CE", ["Messejana"])

    assert ler_disco()["fortaleza, ce"] == ["Messejana"]


def test_escrita_nao_deixa_temporario_para_tras():
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles"])
    registrar_bairros_vistos("Fortaleza, CE", ["Messejana"])
    assert list(bairros._CACHE_PATH.parent.glob("*.tmp")) == []


def test_arquivo_e_json_valido_e_legivel():
    registrar_bairros_vistos("Fortaleza, CE", ["Cocó", "Aracapé"])
    bruto = bairros._CACHE_PATH.read_text(encoding="utf-8")
    # ensure_ascii=False: o arquivo é para ser lido por gente, não só por json
    assert "Cocó" in bruto
    assert json.loads(bruto)["fortaleza, ce"] == ["Aracapé", "Cocó"]


def test_cria_o_diretorio_se_nao_existir(tmp_path, monkeypatch):
    monkeypatch.setattr(bairros, "_CACHE_PATH", tmp_path / "novo" / "sub" / "b.json")
    registrar_bairros_vistos("Fortaleza, CE", ["Meireles"])
    assert bairros._CACHE_PATH.exists()
