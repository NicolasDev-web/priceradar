"""Testes do posicionamento pelo centro do bairro.

ChavesNaMão e ImovelWeb não publicam coordenada nenhuma, e o ChavesNaMão é a
segunda maior fonte — deixá-los fora do mapa esconderia cerca de um terço dos
anúncios. `aplicar_centroide_bairro` usa o que a própria busca já coletou: se
dois ou mais anúncios do Meireles vieram com coordenada real, o centro deles é
uma estimativa honesta de "Meireles".

O que estes testes protegem é a honestidade da estimativa: que ela nunca se
disfarce de endereço, nunca seja calculada com um ponto só, e nunca se alimente
dos próprios palpites.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.geo import (  # noqa: E402
    MINIMO_PARA_CENTROIDE,
    aplicar_centroide_bairro,
    calcular_centroides,
)


def anuncio(bairro=None, lat=None, lng=None, origem=None):
    item = {"bairro": bairro, "latitude": lat, "longitude": lng}
    if origem:
        item["origem_coordenada"] = origem
    return item


# --------------------------------------------------------------------------
# calcular_centroides
# --------------------------------------------------------------------------

def test_centroide_e_a_media_dos_pontos_do_bairro():
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
    ]
    centro = calcular_centroides(itens)["meireles"]
    assert centro[0] == pytest.approx(-3.73)
    assert centro[1] == pytest.approx(-38.51)


def test_bairro_com_um_ponto_nao_gera_centroide():
    """Com 1 ponto o 'centro' é aquele anúncio — precisão que não existe."""
    itens = [anuncio("Meireles", -3.72, -38.50, "exata")]
    assert calcular_centroides(itens) == {}


def test_bairro_com_dois_pontos_gera_centroide():
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
    ]
    assert "meireles" in calcular_centroides(itens)


def test_o_minimo_documentado_e_dois():
    """Se alguém baixar para 1, os dois testes acima explicam o porquê."""
    assert MINIMO_PARA_CENTROIDE == 2


def test_agrupa_ignorando_acento_e_caixa():
    """"Cocó" (payload) e "coco" (slug) são o mesmo bairro."""
    itens = [
        anuncio("Cocó", -3.74, -38.47, "exata"),
        anuncio("coco", -3.76, -38.49, "exata"),
        anuncio("  COCO ", -3.75, -38.48, "exata"),
    ]
    centroides = calcular_centroides(itens)
    assert len(centroides) == 1
    assert centroides["coco"][0] == pytest.approx(-3.75)


def test_anuncio_sem_bairro_nao_entra_no_calculo():
    itens = [
        anuncio(None, -3.72, -38.50, "exata"),
        anuncio("", -3.74, -38.52, "exata"),
    ]
    assert calcular_centroides(itens) == {}


def test_anuncio_sem_coordenada_nao_entra_no_calculo():
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", None, None),
    ]
    assert calcular_centroides(itens) == {}


def test_lista_vazia_devolve_dicionario_vazio():
    assert calcular_centroides([]) == {}


# --------------------------------------------------------------------------
# aplicar_centroide_bairro
# --------------------------------------------------------------------------

def test_posiciona_quem_nao_tem_coordenada_e_rotula_a_estimativa():
    sem = anuncio("Meireles")
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
        sem,
    ]
    assert aplicar_centroide_bairro(itens) == 0

    assert sem["latitude"] == pytest.approx(-3.73)
    assert sem["longitude"] == pytest.approx(-38.51)
    assert sem["origem_coordenada"] == "centroide_bairro"


def test_nao_sobrescreve_coordenada_real():
    real = anuncio("Meireles", -3.7999, -38.5999, "exata")
    itens = [
        real,
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
    ]
    aplicar_centroide_bairro(itens)

    assert real["latitude"] == pytest.approx(-3.7999)
    assert real["origem_coordenada"] == "exata"


def test_conta_como_sem_posicao_quem_nao_tem_bairro():
    orfao = anuncio(None)
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
        orfao,
    ]
    assert aplicar_centroide_bairro(itens) == 1
    assert orfao["latitude"] is None


def test_conta_como_sem_posicao_quando_o_bairro_so_tem_um_ponto():
    sem = anuncio("Messejana")
    itens = [anuncio("Messejana", -3.85, -38.49, "exata"), sem]

    assert aplicar_centroide_bairro(itens) == 1
    assert sem["latitude"] is None
    assert "origem_coordenada" not in sem


def test_devolve_zero_quando_todos_ja_tem_coordenada():
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
    ]
    assert aplicar_centroide_bairro(itens) == 0


def test_lista_vazia_devolve_zero():
    assert aplicar_centroide_bairro([]) == 0


def test_posiciona_pelo_bairro_certo_com_varios_bairros():
    no_meireles = anuncio("Meireles")
    na_messejana = anuncio("Messejana")
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
        anuncio("Messejana", -3.84, -38.48, "exata"),
        anuncio("Messejana", -3.86, -38.50, "exata"),
        no_meireles,
        na_messejana,
    ]
    assert aplicar_centroide_bairro(itens) == 0

    assert no_meireles["latitude"] == pytest.approx(-3.73)
    assert na_messejana["latitude"] == pytest.approx(-3.85)


def test_casa_o_bairro_ignorando_acento():
    sem = anuncio("coco")
    itens = [
        anuncio("Cocó", -3.74, -38.47, "exata"),
        anuncio("Cocó", -3.76, -38.49, "exata"),
        sem,
    ]
    assert aplicar_centroide_bairro(itens) == 0
    assert sem["latitude"] == pytest.approx(-3.75)


# --------------------------------------------------------------------------
# A estimativa não pode se alimentar de si mesma
# --------------------------------------------------------------------------

def test_centroide_nao_se_alimenta_das_proprias_estimativas():
    """
    `calcular_centroides` roda uma vez, sobre o estado inicial. Se alguém
    refatorar para recalcular dentro do laço, cada anúncio posicionado passaria
    a puxar o centro na sua direção e o resultado dependeria da ordem da lista.
    """
    itens = [
        anuncio("Meireles", -3.70, -38.50, "exata"),
        anuncio("Meireles", -3.80, -38.60, "exata"),
        anuncio("Meireles"),
        anuncio("Meireles"),
        anuncio("Meireles"),
    ]
    aplicar_centroide_bairro(itens)

    estimados = [i for i in itens if i.get("origem_coordenada") == "centroide_bairro"]
    assert len(estimados) == 3
    assert all(e["latitude"] == pytest.approx(-3.75) for e in estimados)


def test_segunda_passada_nao_muda_nada():
    """O cache HIT reprocessa a mesma lista — tem que ser idempotente."""
    itens = [
        anuncio("Meireles", -3.72, -38.50, "exata"),
        anuncio("Meireles", -3.74, -38.52, "exata"),
        anuncio("Meireles"),
        anuncio(None),
    ]
    primeira = aplicar_centroide_bairro(itens)
    depois = [dict(i) for i in itens]

    segunda = aplicar_centroide_bairro(itens)

    assert primeira == segunda == 1
    assert itens == depois
