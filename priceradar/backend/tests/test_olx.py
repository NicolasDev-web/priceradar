"""OLX: município certo, URL por cidade/bairro e cadeia de fallback.

Payloads SINTÉTICOS no formato RSC que `scripts/diagnosticar_olx_rsc.py` mostrou
em 27/09/2026 (a rede deste ambiente bloqueia a OLX). Provam a lógica, não o
formato real — isso é o que `scripts/validar_olx_pipeline.py` confere no PC.
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import olximoveis  # noqa: E402


@pytest.fixture(autouse=True)
def _limpa_regioes_aprendidas():
    olximoveis._regioes_aprendidas.clear()
    yield
    olximoveis._regioes_aprendidas.clear()


def ad(i, location=None, regiao="fortaleza-e-regiao", **extra):
    item = {
        "subject": f"Apartamento {i}",
        "priceValue": "R$ 420.000",
        "listId": i,
        "url": f"https://ce.olx.com.br/{regiao}/imoveis/apartamento-{i}",
        "properties": [{"name": "size", "value": "60m²"}, {"name": "rooms", "value": "2"}],
    }
    if location is not None:
        item["location"] = location
    item.update(extra)
    return item


def pagina_html(ads) -> str:
    payload = '0:{"children":{"ads":' + json.dumps(ads, ensure_ascii=False) + "}}"
    # Partido em dois pushes, como o Next.js faz com payload grande.
    meio = len(payload) // 2
    return "".join(
        f"<script>self.__next_f.push({json.dumps([1, parte], ensure_ascii=False)})</script>"
        for parte in (payload[:meio], payload[meio:])
    ) + " " * 1000


# ── Município ────────────────────────────────────────────────────────────────

def test_anuncio_de_outro_municipio_e_descartado():
    descartes = Counter()
    html = pagina_html([
        ad(1, "Caucaia, Icaraí - DDD 85"),
        ad(2, "Fortaleza, Cocó - DDD 85"),
        ad(3, "Eusébio - DDD 85"),
    ])
    resultado = olximoveis.parse_olx_html(html, "fortaleza", descartes=descartes)
    assert [(r["url_anuncio"][-1], r["bairro"]) for r in resultado] == [("2", "Cocó")]
    assert descartes == Counter({"Caucaia": 1, "Eusébio": 1})


def test_location_details_tem_prioridade_sobre_o_texto():
    html = pagina_html([
        ad(1, "Fortaleza, Cocó - DDD 85",
           locationDetails={"municipality": "Caucaia", "neighbourhood": "Icaraí"}),
        ad(2, "texto qualquer",
           locationDetails={"municipality": "Fortaleza", "neighbourhood": "Meireles"}),
    ])
    [anuncio] = olximoveis.parse_olx_html(html, "fortaleza")
    assert anuncio["bairro"] == "Meireles"


def test_ordem_invertida_bairro_cidade_e_corrigida():
    [anuncio] = olximoveis.parse_olx_html(pagina_html([ad(1, "Aldeota, Fortaleza")]), "fortaleza")
    assert anuncio["bairro"] == "Aldeota"


def test_cidade_com_acento_e_hifen_bate():
    html = pagina_html([ad(1, "São Paulo, Moema - DDD 11", regiao="sao-paulo-e-regiao")])
    assert len(olximoveis.parse_olx_html(html, "sao-paulo")) == 1


def test_sem_municipio_so_passa_na_url_por_cidade():
    html = pagina_html([ad(1)])
    assert len(olximoveis.parse_olx_html(html, "fortaleza")) == 1
    descartes = Counter()
    assert olximoveis.parse_olx_html(html, "fortaleza", exigir_municipio=True, descartes=descartes) == []
    assert descartes == Counter({"(sem município)": 1})


# ── URL ──────────────────────────────────────────────────────────────────────

def test_url_por_cidade_com_bairro_quartos_e_pagina():
    url = olximoveis.build_olx_url("fortaleza", "ce", 280000, 500000, quartos=2, bairro="Cocó", pagina=3)
    assert url == (
        "https://www.olx.com.br/imoveis/venda/apartamentos/estado-ce/fortaleza-e-regiao/fortaleza/coco"
        "?ps=280000&pe=500000&ros=2&o=3"
    )


def test_url_sem_regiao_conhecida_usa_texto_no_estado():
    url = olximoveis.build_olx_url("natal", "rn", 200000, 400000)
    assert url == "https://www.olx.com.br/imoveis/venda/apartamentos/estado-rn?ps=200000&pe=400000&q=natal"


def test_url_de_cidade_com_espaco_vira_slug_e_texto():
    assert "q=joao+pessoa" in olximoveis.build_olx_url("joao-pessoa", "pb", 1, 2)


def test_regiao_aprendida_da_url_do_anuncio():
    assert olximoveis.regiao_olx("rn", "natal") is None
    html = pagina_html([ad(1, "Natal, Ponta Negra - DDD 84", regiao="natal-e-regiao")])
    html = html.replace("ce.olx.com.br", "rn.olx.com.br")
    olximoveis.parse_olx_html(html, "natal", exigir_municipio=True)
    assert olximoveis.regiao_olx("rn", "natal") == "natal-e-regiao"
    assert "/estado-rn/natal-e-regiao/natal?" in olximoveis.build_olx_url("natal", "rn", 1, 2)


def test_anuncio_de_outra_cidade_nao_ensina_regiao():
    html = pagina_html([ad(1, "Parnamirim - DDD 84", regiao="natal-e-regiao")]).replace("ce.olx", "rn.olx")
    olximoveis.parse_olx_html(html, "natal", exigir_municipio=True)
    assert olximoveis.regiao_olx("rn", "natal") is None


# ── Coleta (fallback) ────────────────────────────────────────────────────────

def _coletar(monkeypatch, respostas: dict[str, str | None], **kw):
    pedidas: list[str] = []

    async def falso_buscar_html(url, portal):
        pedidas.append(url)
        for trecho, html in respostas.items():
            if trecho in url:
                return html
        return None

    monkeypatch.setattr(olximoveis, "buscar_html", falso_buscar_html)
    monkeypatch.setattr(olximoveis, "MAX_PAGINAS_OLX", 2)
    args = dict(cidade="fortaleza", estado="ce", preco_min=280000, preco_max=500000, quartos=2)
    args.update(kw)
    return asyncio.run(olximoveis.scrape_olximoveis(**args)), pedidas


def test_coleta_pela_cidade_e_pagina(monkeypatch):
    # A ordem importa: a URL da p2 também contém o trecho da p1.
    respostas = {
        "&o=2": pagina_html([ad(2, "Fortaleza, Aldeota - DDD 85")]),
        "fortaleza-e-regiao/fortaleza?": pagina_html([ad(1, "Fortaleza, Cocó - DDD 85")]),
    }
    resultado, pedidas = _coletar(monkeypatch, respostas)
    assert sorted(r["bairro"] for r in resultado) == ["Aldeota", "Cocó"]
    assert all("fortaleza-e-regiao/fortaleza?" in u for u in pedidas)
    assert olximoveis.ULTIMA_COLETA["modo"] == "cidade"


def test_bairro_que_nao_abre_cai_para_a_cidade(monkeypatch):
    respostas = {"fortaleza-e-regiao/fortaleza?": pagina_html([ad(1, "Fortaleza, Cocó - DDD 85")])}
    resultado, pedidas = _coletar(monkeypatch, respostas, bairro="Cocó")
    assert "/fortaleza/coco?" in pedidas[0]
    assert len(resultado) == 1 and olximoveis.ULTIMA_COLETA["modo"] == "cidade"


def test_bairro_sem_oferta_nao_varre_a_cidade(monkeypatch):
    respostas = {"/fortaleza/coco?": pagina_html([])}
    resultado, pedidas = _coletar(monkeypatch, respostas, bairro="Cocó")
    assert resultado == [] and len(pedidas) == 1


def test_cidade_que_nao_abre_cai_para_o_estado_com_filtro(monkeypatch):
    respostas = {"&o=2": pagina_html([]), "estado-ce?": pagina_html([ad(1, "Caucaia, Icaraí - DDD 85"), ad(2, "Fortaleza, Cocó - DDD 85")])}
    resultado, _ = _coletar(monkeypatch, respostas)
    assert [r["bairro"] for r in resultado] == ["Cocó"]
    assert olximoveis.ULTIMA_COLETA["modo"] == "estado"
    assert olximoveis.ULTIMA_COLETA["descartados_outro_municipio"] == {"Caucaia": 1}


def test_regiao_aprendida_que_falha_e_esquecida(monkeypatch):
    olximoveis._regioes_aprendidas[("rn", "natal")] = "regiao-errada"
    _coletar(monkeypatch, {}, cidade="natal", estado="rn")
    assert olximoveis.regiao_olx("rn", "natal") is None


def test_busca_cria_uma_tarefa_olx_por_bairro(monkeypatch):
    from models import BuscaRequest
    from services import search

    chamadas: list = []

    async def vazio(*a, **k):
        return []

    async def olx_falso(*args):
        chamadas.append(args[-1])
        return []

    for nome in ("scrape_vivareal", "scrape_zapimoveis", "scrape_imovelweb", "scrape_chavesnamao"):
        monkeypatch.setattr(search, nome, vazio)
    monkeypatch.setattr(search, "scrape_olximoveis", olx_falso)
    monkeypatch.setattr(search, "OLX_HABILITADO", True)
    monkeypatch.setattr(search, "MOCK_MODE", False)
    monkeypatch.setattr(search, "registrar_resultado", lambda *a, **k: None)

    request = BuscaRequest(cidade="Fortaleza, CE", preco_min=280000, preco_max=500000, bairros=["Cocó", "Aldeota"])
    asyncio.run(search.executar_busca(request))
    assert sorted(chamadas) == ["Aldeota", "Cocó"]
