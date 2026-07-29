"""Testes do parser do ChavesNaMão e da blindagem de outliers.

O parser do ChavesNaMão é testado contra um recorte do JSON-LD real do portal
(capturado em 29/07/2026), para que uma mudança de layout apareça como teste
vermelho em vez de virar silenciosamente zero resultado.
"""
import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.chavesnamao import (  # noqa: E402
    _area_de_floorsize,
    _build_url,
    _extrair_ofertas_jsonld,
    _parse_oferta,
)
from scraper.parser import extrair_construtora, extrair_nome_empreendimento  # noqa: E402
from services.rf_refiner import _filtrar_preco_entrada  # noqa: E402


# Recorte fiel do JSON-LD servido pelo ChavesNaMão.
_OFERTA_REAL = {
    "@type": "Offer",
    "name": "Apartamento com 3 quartos à venda em São João do Tauape, Fortaleza",
    "url": "https://www.chavesnamao.com.br/imovel/apartamento-a-venda-3-quartos-ce-fortaleza-sao-joao-do-tauape-RS190000/id-44728966/",
    "price": "190000",
    "itemOffered": {
        "@type": "Apartment",
        "numberOfRooms": 3,
        "numberOfBedrooms": 3,
        "numberOfBathroomsTotal": 3,
        "floorSize": {"@type": "QuantitativeValue", "unitText": "63m²", "unitCode": "MTK"},
        "address": {"@type": "PostalAddress", "addressLocality": "São João do Tauape"},
    },
    "offeredBy": {"@type": "RealEstateAgent", "name": "CONEXÃO 7"},
}


def _html_com(ofertas):
    bloco = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "offers": {"@type": "ItemList", "numberOfItems": 9641, "itemListElement": ofertas},
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(bloco)}</script></head><body></body></html>'


# ── Paginação (o bug silencioso) ─────────────────────────────────────────────

def test_paginacao_usa_pg_e_nao_pagina():
    """Com `&pagina=` o site devolve sempre a página 1 sem sinalizar erro."""
    url = _build_url("fortaleza", "ce", 280_000, 500_000, None, pagina=3)
    assert "pg=3" in url
    assert "pagina=3" not in url


def test_tipo_e_quartos_vao_no_path():
    """Na query string o site ignora e devolve casas e terrenos junto."""
    url = _build_url("fortaleza", "ce", 280_000, 500_000, 2, pagina=1)
    assert "/apartamentos-a-venda/" in url
    assert "/2-quartos/" in url


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_extrai_ofertas_do_bloco_real_estate_listing():
    assert len(_extrair_ofertas_jsonld(_html_com([_OFERTA_REAL, _OFERTA_REAL]))) == 2


def test_html_sem_o_bloco_nao_quebra():
    assert _extrair_ofertas_jsonld("<html><body>nada</body></html>") == []


def test_parse_de_oferta_real():
    item = _parse_oferta(_OFERTA_REAL, "fortaleza")
    assert item is not None
    assert item["preco"] == 190_000.0
    assert item["area_m2"] == 63.0
    assert item["quartos"] == 3
    assert item["banheiros"] == 3
    assert item["bairro"] == "São João do Tauape"
    assert item["portal"] == "chavesnamao"
    assert item["preco_m2"] == round(190_000 / 63, 2)


def test_area_extraida_de_floorsize():
    assert _area_de_floorsize({"floorSize": {"unitText": "63m²"}}) == 63.0
    assert _area_de_floorsize({"floorSize": {"unitText": "63,5 m²"}}) == 63.5
    assert _area_de_floorsize({}) is None


def test_ignora_imovel_que_nao_e_apartamento():
    """A listagem mistura casa, terreno e prédio mesmo com filtro de tipo."""
    casa = json.loads(json.dumps(_OFERTA_REAL))
    casa["itemOffered"]["@type"] = "SingleFamilyResidence"
    assert _parse_oferta(casa, "fortaleza") is None


def test_quartos_como_string_vira_int():
    """O JSON-LD ora traz número, ora string — str×int quebrava o pipeline."""
    oferta = json.loads(json.dumps(_OFERTA_REAL))
    oferta["itemOffered"]["numberOfBedrooms"] = "3"
    assert _parse_oferta(oferta, "fortaleza")["quartos"] == 3


def test_sem_area_e_descartado():
    oferta = json.loads(json.dumps(_OFERTA_REAL))
    del oferta["itemOffered"]["floorSize"]
    assert _parse_oferta(oferta, "fortaleza") is None


# ── Blindagem de outliers ────────────────────────────────────────────────────

def _item(preco_m2, quartos=2):
    return {"cidade": "fortaleza", "quartos": quartos, "preco_m2": preco_m2,
            "nome_anuncio": "Apartamento 2 quartos"}


def test_corta_outlier_alto_e_baixo():
    """Antes só havia corte inferior — por isso passavam anúncios de 18k-26k/m²."""
    itens = [_item(7000), _item(7200), _item(7100), _item(6900), _item(7300),
             _item(2500),    # preço de entrada
             _item(18414)]   # área agregada / erro de parsing
    filtrados, removidos = _filtrar_preco_entrada(itens)
    assert removidos == 2
    valores = [i["preco_m2"] for i in filtrados]
    assert 2500 not in valores and 18414 not in valores


def test_nao_corta_com_grupo_pequeno():
    """Com 2 amostras não há mediana confiável — não filtra."""
    _, removidos = _filtrar_preco_entrada([_item(7000), _item(2000)])
    assert removidos == 0


def test_agrupa_por_tipologia():
    """1 quarto custa mais por m² que 3 quartos — comparar entre grupos cortaria válidos."""
    itens = [_item(14000, 1), _item(14200, 1), _item(13800, 1),
             _item(6000, 3), _item(6100, 3), _item(5900, 3)]
    _, removidos = _filtrar_preco_entrada(itens)
    assert removidos == 0


# ── Extração de construtora e nome (melhor vazio que errado) ─────────────────



@pytest.mark.parametrize("titulo,descricao", [
    ("Apartamento", "Sky lounge e piscina no rooftop"),          # "Sky" não é construtora
    ("Cobertura", "Imóvel próximo ao Parque Estadual do Cocó"),  # parque, não empreendimento
    ("Apartamento", "LOCALIZAÇÃO PRIVILEGIADA\nÓtimo apto"),     # chamada de marketing
    ("Apto", "Vendido por Imobiliária XYZ LTDA"),                # razão social de corretora
    ("Apartamento", "Fica em Morada Nova, ótima região"),        # cidade do Ceará
    ("Apto", "Perto do Shopping Iguatemi"),                      # equipamento urbano
])
def test_nao_inventa_construtora_nem_nome(titulo, descricao):
    assert extrair_construtora(titulo, descricao) is None
    assert extrair_nome_empreendimento(descricao) is None


def test_reconhece_construtora_legitima():
    assert extrair_construtora("Apartamento MRV", "Empreendimento da MRV Engenharia") == "MRV"


@pytest.mark.parametrize("descricao,esperado", [
    ("Residencial Vista Bela, ótimo apartamento", "Residencial Vista Bela"),
    ("Condomínio Porto Freire Village", "Condomínio Porto Freire Village"),
    ("Edifício Solar das Águas", "Edifício Solar das Águas"),
])
def test_reconhece_empreendimento_legitimo(descricao, esperado):
    assert extrair_nome_empreendimento(descricao) == esperado
