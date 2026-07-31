"""Testes da extração de coordenada e bairro do payload RSC do Grupo ZAP.

O payload não é documentado e pode mudar sem aviso — é a peça mais frágil da
coleta. Os dois blocos abaixo são recortes literais de
`https://www.vivareal.com.br/venda/ceara/fortaleza/apartamento_residencial/`,
capturados em 31/07/2026 (1,3 MB de HTML, 41 objetos no RSC).

Dois detalhes que só a captura real prova, e que quebrariam a extração inteira
em silêncio se mudassem:

1. **O acento chega literal** — `"neighborhood":"Cocó"`, não `"Coc\\u00f3"`.
   `_payload_rsc` só desfaz o escape de aspas; um escape unicode passaria
   direto e o bairro viraria lixo. (O payload *tem* `\\u00xx` em outros
   campos, então isso não é hipótese.)
2. **O href vem com barras cruas** — `https://`, não `https:\\/\\/`. Escapado,
   o padrão não casaria nada e o índice seria sempre vazio.

O anúncio do Cocó é o caso de ouro: o slug da URL diz `coco` e o payload diz
`Cocó`. Um recorte só prova as duas coisas.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.rsc_grupozap import (  # noqa: E402
    aplicar_localizacao,
    chave_url,
    indexar_localizacoes,
)

# Recortes literais da captura de 31/07/2026.
_PASSARE = (
    '"href":"https://www.vivareal.com.br/imovel/apartamento-2-quartos-passare-'
    'fortaleza-com-garagem-59m2-venda-RS205000-id-2901647898/","business":"SALE",'
    '"address":{"city":"Fortaleza","state":"$undefined","stateAcronym":"CE",'
    '"neighborhood":"Passaré","isApproximateLocation":false,"streetNumber":"333",'
    '"street":"Rua Trajano de Morais","locationId":"$undefined",'
    '"coordinates":{"latitude":-3.811158,"longitude":-38.523427}}'
)
_COCO = (
    '"href":"https://www.vivareal.com.br/imovel/apartamento-2-quartos-coco-'
    'fortaleza-com-garagem-70m2-venda-RS577000-id-2889641816/","business":"SALE",'
    '"address":{"city":"Fortaleza","state":"$undefined","stateAcronym":"CE",'
    '"neighborhood":"Cocó","isApproximateLocation":false,"streetNumber":"1100",'
    '"street":"Rua Andrade Furtado","locationId":"$undefined",'
    '"coordinates":{"latitude":-3.74631,"longitude":-38.479013}}'
)

URL_PASSARE = (
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-passare-fortaleza"
    "-com-garagem-59m2-venda-RS205000-id-2901647898/"
)
URL_COCO = (
    "https://www.vivareal.com.br/imovel/apartamento-2-quartos-coco-fortaleza"
    "-com-garagem-70m2-venda-RS577000-id-2889641816/"
)


def montar_html(*blocos: str) -> str:
    """Embrulha os blocos como o Next serve: chunk com aspas escapadas."""
    corpo = ",".join(blocos).replace('"', '\\"')
    return f'<html><body><script>self.__next_f.push([1,"{corpo}"])</script></body></html>'


@pytest.fixture
def indice():
    return indexar_localizacoes(montar_html(_PASSARE, _COCO))


# --------------------------------------------------------------------------
# Payload real
# --------------------------------------------------------------------------

def test_indexa_os_dois_anuncios_do_payload_real(indice):
    assert set(indice) == {chave_url(URL_PASSARE), chave_url(URL_COCO)}


def test_coordenadas_sao_as_do_payload(indice):
    assert indice[chave_url(URL_PASSARE)]["latitude"] == pytest.approx(-3.811158)
    assert indice[chave_url(URL_PASSARE)]["longitude"] == pytest.approx(-38.523427)
    assert indice[chave_url(URL_COCO)]["latitude"] == pytest.approx(-3.74631)


def test_bairro_chega_acentuado_e_nao_escapado(indice):
    """Se o portal passar a mandar `Coc\\u00f3`, este teste cai — e é o aviso."""
    assert indice[chave_url(URL_COCO)]["bairro"] == "Cocó"
    assert indice[chave_url(URL_PASSARE)]["bairro"] == "Passaré"


def test_aproximada_falsa_quando_o_portal_declara_false(indice):
    assert indice[chave_url(URL_COCO)]["aproximada"] is False


def test_aproximada_verdadeira_quando_o_portal_declara_true():
    bloco = _COCO.replace('"isApproximateLocation":false', '"isApproximateLocation":true')
    indice = indexar_localizacoes(montar_html(bloco))
    assert indice[chave_url(URL_COCO)]["aproximada"] is True


def test_aproximada_falsa_quando_o_campo_nao_vem():
    """`isApproximateLocation` é opcional — a ausência não pode zerar o anúncio."""
    bloco = _COCO.replace('"isApproximateLocation":false,', "")
    indice = indexar_localizacoes(montar_html(bloco))
    assert indice[chave_url(URL_COCO)]["aproximada"] is False
    assert indice[chave_url(URL_COCO)]["latitude"] == pytest.approx(-3.74631)


# --------------------------------------------------------------------------
# Degradar em vez de explodir
# --------------------------------------------------------------------------

def test_html_sem_payload_devolve_vazio():
    assert indexar_localizacoes("<html><body>sem RSC nenhum</body></html>") == {}


def test_html_vazio_devolve_vazio():
    assert indexar_localizacoes("") == {}


def test_payload_cortado_antes_da_coordenada_devolve_vazio():
    """Um chunk pode cortar no meio de um objeto — não pode virar exceção."""
    cortado = _COCO[: _COCO.index('"coordinates"')]
    assert indexar_localizacoes(montar_html(cortado)) == {}


def test_lixo_dentro_do_push_nao_levanta():
    assert indexar_localizacoes('<script>self.__next_f.push([1,"}{[[ ,,, "])</script>') == {}


def test_href_escapado_nao_casa_mas_nao_explode():
    """Se o Next passar a escapar as barras, o índice fica vazio — não quebrado."""
    escapado = _COCO.replace("https://", "https:\\/\\/")
    assert indexar_localizacoes(montar_html(escapado)) == {}


# --------------------------------------------------------------------------
# Barreira geográfica: (0,0) e outro país viram pin no Golfo da Guiné
# --------------------------------------------------------------------------

@pytest.mark.parametrize("lat,lng", [
    (40.712776, -74.005974),   # Nova York
    (0, 0),                    # Golfo da Guiné — o clássico "coordenada faltando"
    (-3.74631, 2.35),          # longitude europeia
    (51.5, -0.12),             # Londres
])
def test_coordenada_fora_do_brasil_e_barrada(lat, lng):
    bloco = _COCO.replace(
        '"latitude":-3.74631,"longitude":-38.479013',
        f'"latitude":{lat},"longitude":{lng}',
    )
    assert indexar_localizacoes(montar_html(bloco)) == {}


@pytest.mark.parametrize("lat,lng", [
    (-33.75, -53.4),    # extremo sul, Chuí/RS
    (4.5, -60.0),       # extremo norte, Roraima
    (-3.74631, -38.479013),
])
def test_coordenada_dentro_da_caixa_do_brasil_entra(lat, lng):
    bloco = _COCO.replace(
        '"latitude":-3.74631,"longitude":-38.479013',
        f'"latitude":{lat},"longitude":{lng}',
    )
    assert len(indexar_localizacoes(montar_html(bloco))) == 1


# --------------------------------------------------------------------------
# O erro mais caro: pin no lugar errado com cara de coordenada exata
# --------------------------------------------------------------------------

def test_anuncio_sem_coordenada_nao_herda_a_do_seguinte():
    """
    O anúncio A não tem `coordinates`. Sem o ponto temperado no padrão, a
    janela atravessaria o início de B e plotaria A no endereço de B — marcado
    como `exata`, que é o pior jeito de errar.
    """
    sem_coord = _PASSARE[: _PASSARE.index(',"coordinates"')] + "}"
    indice = indexar_localizacoes(montar_html(sem_coord, _COCO))

    assert chave_url(URL_PASSARE) not in indice
    assert chave_url(URL_COCO) in indice


def test_anuncio_seguinte_continua_indexado_mesmo_colado():
    """A garantia não pode custar o anúncio de trás: B tem que sobreviver."""
    sem_coord = '"href":"https://www.vivareal.com.br/imovel/a-id-1/","neighborhood":"X"'
    indice = indexar_localizacoes(montar_html(sem_coord, _COCO))

    assert len(indice) == 1
    assert indice[chave_url(URL_COCO)]["bairro"] == "Cocó"


def test_bairro_de_um_anuncio_nao_casa_com_a_coordenada_de_outro():
    indice = indexar_localizacoes(montar_html(_PASSARE, _COCO))
    assert indice[chave_url(URL_PASSARE)]["latitude"] == pytest.approx(-3.811158)
    assert indice[chave_url(URL_COCO)]["latitude"] == pytest.approx(-3.74631)


# --------------------------------------------------------------------------
# chave_url — o join entre JSON-LD e RSC
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url,esperado", [
    ("https://x.com.br/imovel/a-id-1/", "https://x.com.br/imovel/a-id-1"),
    ("https://x.com.br/imovel/a-id-1", "https://x.com.br/imovel/a-id-1"),
    ("https://x.com.br/imovel/a-id-1/?utm=x", "https://x.com.br/imovel/a-id-1"),
    ("https://x.com.br/imovel/a-id-1/#fotos", "https://x.com.br/imovel/a-id-1"),
    ("https://x.com.br/imovel/a-id-1/?a=1#b", "https://x.com.br/imovel/a-id-1"),
    ("", ""),
])
def test_chave_url_normaliza(url, esperado):
    assert chave_url(url) == esperado


def test_chave_url_aceita_none():
    assert chave_url(None) == ""


# --------------------------------------------------------------------------
# aplicar_localizacao
# --------------------------------------------------------------------------

def test_enriquece_o_item_pela_url_com_query(indice):
    item = {"url_anuncio": URL_COCO + "?utm_source=x", "bairro": "Coco"}
    aplicar_localizacao(item, indice)

    assert item["latitude"] == pytest.approx(-3.74631)
    assert item["longitude"] == pytest.approx(-38.479013)
    assert item["origem_coordenada"] == "exata"


def test_bairro_do_payload_sobrescreve_o_adivinhado_do_slug(indice):
    """`extrair_bairro_do_slug` acerta ~83% e nunca acentua: o portal ganha."""
    item = {"url_anuncio": URL_COCO, "bairro": "Coco"}
    aplicar_localizacao(item, indice)
    assert item["bairro"] == "Cocó"


def test_origem_aproximada_quando_o_portal_declara():
    bloco = _COCO.replace('"isApproximateLocation":false', '"isApproximateLocation":true')
    item = {"url_anuncio": URL_COCO}
    aplicar_localizacao(item, indexar_localizacoes(montar_html(bloco)))
    assert item["origem_coordenada"] == "aproximada_portal"


def test_url_desconhecida_deixa_o_item_intacto(indice):
    item = {"url_anuncio": "https://outro.com.br/imovel/z-id-99/", "bairro": "Aldeota"}
    aplicar_localizacao(item, dict(indice))
    assert item == {"url_anuncio": "https://outro.com.br/imovel/z-id-99/", "bairro": "Aldeota"}


def test_item_sem_url_nao_levanta(indice):
    item = {"bairro": "Aldeota"}
    aplicar_localizacao(item, indice)
    assert "latitude" not in item


def test_bairro_vazio_no_payload_preserva_o_que_ja_havia():
    """Não apagar um palpite razoável para pôr string vazia no lugar."""
    bloco = _COCO.replace('"neighborhood":"Cocó"', '"neighborhood":""')
    item = {"url_anuncio": URL_COCO, "bairro": "Coco"}
    aplicar_localizacao(item, indexar_localizacoes(montar_html(bloco)))

    assert item["bairro"] == "Coco"
    assert item["latitude"] == pytest.approx(-3.74631)


def test_indice_vazio_nao_toca_em_nada():
    item = {"url_anuncio": URL_COCO, "bairro": "Coco"}
    aplicar_localizacao(item, {})
    assert item == {"url_anuncio": URL_COCO, "bairro": "Coco"}
