"""Cada scraper entrega `fotos` no dict do anúncio.

ATENÇÃO: os trechos abaixo são SINTÉTICOS, montados no formato que cada portal
costuma publicar (schema.org, __NEXT_DATA__, cards HTML). Não são capturas
reais — a rede do ambiente onde isto foi escrito bloqueia os portais. Eles
provam a ligação (o campo chega, formato estranho não derruba o anúncio), não
que o portal de fato publica a foto ali. Isso é o que
`scripts/diagnosticar_fotos.py` confirma, numa máquina com acesso.
"""
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import chavesnamao, imovelweb, olximoveis, quintoandar, vivareal, zapimoveis  # noqa: E402


def _jsonld_itemlist(image) -> str:
    item = {
        "@type": "Apartment",
        "name": "Apartamento 2 quartos à venda",
        "url": "https://www.vivareal.com.br/imovel/apto-2-quartos-meireles-fortaleza-id-1/",
        "offers": {"price": 400000},
        "floorSize": {"value": 60},
        "numberOfBedrooms": 2,
        "numberOfBathroomsTotal": 2,
        "address": {"streetAddress": "Rua X"},
        "image": image,
    }
    dados = {"@type": "ItemList", "itemListElement": [{"item": item}]}
    return f'<script type="application/ld+json">{json.dumps(dados)}</script>'


def test_grupo_zap_le_image_do_jsonld():
    molde = "https://resizedimgs.vivareal.com/{action}/{width}x{height}/named.images.sp/h/1.jpg"
    for modulo in (vivareal, zapimoveis):
        [anuncio] = modulo._parse_json_ld(_jsonld_itemlist([molde, "https://img/2.jpg"]), "fortaleza")
        assert anuncio["fotos"][0].startswith("https://resizedimgs.vivareal.com/fit-in/870x653/")
        assert len(anuncio["fotos"]) == 2


def test_grupo_zap_sem_image_nao_perde_o_anuncio():
    [anuncio] = vivareal._parse_json_ld(_jsonld_itemlist(None), "fortaleza")
    assert anuncio["fotos"] == []
    assert anuncio["preco"] == 400000


def test_chavesnamao_le_image_do_imovel_ou_da_oferta():
    oferta = {
        "price": 400000, "name": "Apto 2 quartos", "url": "https://www.chavesnamao.com.br/imovel/1",
        "itemOffered": {"@type": "Apartment", "floorSize": {"unitText": "60m²"},
                        "image": {"@type": "ImageObject", "url": "/fotos/1.jpg"}},
    }
    anuncio = chavesnamao._parse_oferta(oferta, "fortaleza")
    assert anuncio["fotos"] == ["https://www.chavesnamao.com.br/fotos/1.jpg"]

    del oferta["itemOffered"]["image"]
    oferta["image"] = "https://cdn.chavesnamao.com.br/2.jpg"
    assert chavesnamao._parse_oferta(oferta, "fortaleza")["fotos"] == ["https://cdn.chavesnamao.com.br/2.jpg"]


def test_quintoandar_monta_url_do_cdn():
    house = {"forSale": True, "type": "Apartamento", "salePrice": 400000, "area": 60,
             "bedrooms": 2, "id": 9, "coverImage": "original1.jpg", "imageList": ["original2.jpg"]}
    anuncio = quintoandar._parse_house(house, "fortaleza", 0, 10**7)
    assert anuncio["fotos"] == [quintoandar.QA_IMG + "original1.jpg", quintoandar.QA_IMG + "original2.jpg"]


def test_imovelweb_le_foto_do_card():
    html = """<div data-posting-type="PROPERTY" data-to-posting="/propriedades/1.html">
      <img data-src="https://imgbr.imovelwebcdn.com/avisos/1.jpg">
      <div class="price-container">R$ 400.000</div>
      <div class="main-features"><span class="main-features-span">60 m²</span></div>
    </div>"""
    card = BeautifulSoup(html, "lxml").select_one("div")
    anuncio = imovelweb._parse_card(card, "fortaleza", 0, 10**7)
    assert anuncio["fotos"] == ["https://imgbr.imovelwebcdn.com/avisos/1.jpg"]


def test_olx_le_foto_do_card():
    html = """<ul><li data-lurker-detail="ad_list">
      <picture><img src="https://img.olx.com.br/images/1.jpg"></picture>
      <h2 class="title">Apartamento 2 quartos</h2>
      <h3 class="price">R$ 400.000</h3>
      <ul class="tags"><li>60m²</li><li>2 quartos</li></ul>
      <a data-lurker-detail="ad_title" href="https://ce.olx.com.br/1">x</a>
    </li></ul>"""
    [anuncio] = olximoveis.parse_olx_html(html, "fortaleza")
    assert anuncio["fotos"] == ["https://img.olx.com.br/images/1.jpg"]
