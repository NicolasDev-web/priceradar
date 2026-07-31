"""Testes do filtro que alimenta a sugestão de bairros.

A sugestão só deve aprender bairro que veio ESTRUTURADO do portal.
`aplicar_localizacao` grava `origem_coordenada` e `bairro` na mesma passagem,
então `exata` e `aproximada_portal` são exatamente "este nome veio do payload".

O resto vem de `extrair_bairro_do_slug`: ~83% de acerto e sempre sem acento.
Registrar isso encheria a lista de sugestões com palpite errado e sem acento —
justamente o que o payload RSC foi coletado para consertar.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.search import bairros_para_registrar  # noqa: E402


def item(origem, bairro):
    return {"origem_coordenada": origem, "bairro": bairro}


def test_registra_bairro_de_coordenada_exata():
    assert bairros_para_registrar([item("exata", "Cocó")]) == ["Cocó"]


def test_registra_bairro_de_coordenada_aproximada_do_portal():
    """O pin é aproximado, mas o NOME do bairro veio do payload do mesmo jeito."""
    assert bairros_para_registrar([item("aproximada_portal", "Aracapé")]) == ["Aracapé"]


@pytest.mark.parametrize("origem", ["centroide_bairro", None, "", "outra_coisa"])
def test_ignora_bairro_que_nao_veio_do_portal(origem):
    assert bairros_para_registrar([item(origem, "Aldeota")]) == []


def test_ignora_item_sem_a_chave_de_origem():
    assert bairros_para_registrar([{"bairro": "Aldeota"}]) == []


@pytest.mark.parametrize("bairro", [None, "", "   "])
def test_ignora_bairro_vazio(bairro):
    assert bairros_para_registrar([item("exata", bairro)]) == []


def test_apara_espaco_nas_bordas():
    assert bairros_para_registrar([item("exata", "  Meireles  ")]) == ["Meireles"]


def test_nao_repete_o_mesmo_bairro():
    itens = [item("exata", "Meireles"), item("exata", "Meireles")]
    assert bairros_para_registrar(itens) == ["Meireles"]


def test_dedup_ignora_acento_e_caixa_e_fica_com_o_primeiro():
    itens = [item("exata", "Cocó"), item("exata", "coco"), item("exata", "COCO")]
    assert bairros_para_registrar(itens) == ["Cocó"]


def test_preserva_a_ordem_em_que_apareceram():
    itens = [item("exata", "Messejana"), item("exata", "Aldeota"), item("exata", "Cocó")]
    assert bairros_para_registrar(itens) == ["Messejana", "Aldeota", "Cocó"]


def test_lista_vazia():
    assert bairros_para_registrar([]) == []


def test_busca_sem_nenhuma_coordenada_nao_registra_nada():
    """Praça onde só ChavesNaMão e ImovelWeb responderam."""
    itens = [item(None, "Aldeota"), item(None, "Centro")]
    assert bairros_para_registrar(itens) == []


def test_mistura_realista():
    """VivaReal/Zap com payload, ChavesNaMão estimado, um sem bairro nenhum."""
    itens = [
        item("exata", "Cocó"),
        item("centroide_bairro", "Coco"),      # mesmo bairro, mas sem acento
        item("exata", "Meireles"),
        item("aproximada_portal", "Passaré"),
        item(None, "Papicu"),
        item("exata", None),
    ]
    assert bairros_para_registrar(itens) == ["Cocó", "Meireles", "Passaré"]
