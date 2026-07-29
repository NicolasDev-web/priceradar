"""Testes da classificação torre × bloco.

O princípio que estes testes protegem: **ausência de sinal não é evidência de
ausência**. "Sem elevador" aparece em ZERO de 30 anúncios medidos — ninguém
anuncia que o prédio não tem elevador. Então um anúncio que não menciona nada
é `indefinido`, nunca `provavel_bloco`.

Se alguém "melhorar" isso empurrando os indefinidos para bloco, metade da base
passa a afirmar algo falso sem que ninguém perceba. Estes testes falham nesse
caso.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.parser import (  # noqa: E402
    INDEFINIDO,
    PROVAVEL_BLOCO,
    TORRE,
    classificar_edificacao,
    extrair_amenidades,
)


# ── Evidência positiva de torre ──────────────────────────────────────────────

def test_amenidade_elevator_indica_torre():
    """Sinal estruturado do JSON-LD, o mais confiável."""
    assert classificar_edificacao(["Pets Allowed", "Elevator"], "Apartamento") == TORRE


def test_elevador_no_texto_indica_torre():
    assert classificar_edificacao([], "Apartamento com elevador e piscina") == TORRE


def test_amenidade_em_portugues_tambem_conta():
    assert classificar_edificacao(["Elevador"], "") == TORRE


@pytest.mark.parametrize("texto", [
    "Apartamento no 15º andar", "Unidade no 8 andar", "5º pavimento",
])
def test_andar_alto_indica_torre(texto):
    """Prédio sem elevador raramente passa de 4 pavimentos."""
    assert classificar_edificacao([], texto) == TORRE


def test_usa_o_maior_andar_citado():
    """'do 2º ao 12º andar' descreve um prédio alto, não um de 2 andares."""
    assert classificar_edificacao([], "Unidades do 2º ao 12º andar") == TORRE


# ── Inferência fraca de bloco ────────────────────────────────────────────────

@pytest.mark.parametrize("texto", ["Apartamento no 2º andar", "Unidade no 4 andar"])
def test_andar_baixo_sem_elevador_e_provavel_bloco(texto):
    assert classificar_edificacao([], texto) == PROVAVEL_BLOCO


def test_andar_baixo_com_elevador_e_torre():
    """O elevador manda: prédio alto pode ter unidade em andar baixo."""
    assert classificar_edificacao(["Elevator"], "Apartamento no 2º andar") == TORRE


# ── O ponto central: indefinido não é bloco ──────────────────────────────────

@pytest.mark.parametrize("amenidades,texto", [
    ([], "Apartamento 2 quartos com garagem"),
    (["Barbecue Grill", "Playground"], "Ótimo apartamento em condomínio fechado"),
    ([], ""),
    (None, None),
])
def test_sem_sinal_algum_fica_indefinido(amenidades, texto):
    """
    Não menciona elevador nem andar ⇒ INDEFINIDO, jamais PROVAVEL_BLOCO.
    Marcar como bloco o que apenas não foi declarado é afirmar o que não se sabe.
    """
    assert classificar_edificacao(amenidades, texto) == INDEFINIDO


def test_amenidades_presentes_sem_elevador_nao_viram_bloco():
    """O anunciante listou amenidades e não citou elevador — ainda assim não
    se pode concluir que o prédio não tem."""
    amenidades = ["Pets Allowed", "Furnished", "Garden", "Party Hall"]
    assert classificar_edificacao(amenidades, "Apartamento amplo") == INDEFINIDO


def test_numero_absurdo_de_andar_e_ignorado():
    """Ruído de parsing não pode virar classificação."""
    assert classificar_edificacao([], "Apartamento 999 andar") == INDEFINIDO


# ── Extração de amenidades do JSON-LD ────────────────────────────────────────

def test_extrai_amenidades_do_formato_do_portal():
    item = {"amenityFeature": [
        {"@type": "LocationFeatureSpecification", "name": "Amenity", "value": "Elevator"},
        {"@type": "LocationFeatureSpecification", "name": "Amenity", "value": "Garden"},
    ]}
    assert extrair_amenidades(item) == ["Elevator", "Garden"]


@pytest.mark.parametrize("item", [{}, {"amenityFeature": None}, {"amenityFeature": []}])
def test_sem_amenidades_devolve_lista_vazia(item):
    assert extrair_amenidades(item) == []


def test_tolera_amenidade_como_dict_unico():
    assert extrair_amenidades({"amenityFeature": {"value": "Elevator"}}) == ["Elevator"]
