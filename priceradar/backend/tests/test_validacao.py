"""Testes da validação de fronteira.

Os casos vêm de anúncios reais que passaram pelo pipeline antes da correção
e contaminaram o KPI. Cada teste trava uma regressão específica.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.validacao import filtrar_anuncios, validar_anuncio  # noqa: E402


class Req:
    """Stub de BuscaRequest com só o que a validação usa."""
    def __init__(self, quartos=None, preco_min=280_000, preco_max=500_000):
        self.quartos = quartos
        self.preco_min = preco_min
        self.preco_max = preco_max


def anuncio(**kw):
    base = {
        "nome_anuncio": "Apartamento à venda com 2 quartos",
        "descricao": "Apartamento bem localizado",
        "url_anuncio": "https://exemplo.com/imovel/1",
        "preco": 400_000.0,
        "area_m2": 60.0,
        "preco_m2": 6_666.67,
        "quartos": 2,
        "cidade": "fortaleza",
    }
    base.update(kw)
    return base


# ── Locação ──────────────────────────────────────────────────────────────────

def test_rejeita_anuncio_de_aluguel_pelo_titulo():
    # Caso real: "Apartamento para alugar com 3 quartos" numa busca de venda
    ok, motivo = validar_anuncio(anuncio(nome_anuncio="Apartamento para alugar com 3 quartos"), Req())
    assert not ok and motivo == "locacao"


def test_rejeita_aluguel_pela_url():
    ok, motivo = validar_anuncio(anuncio(url_anuncio="https://x.com/aluguel/apto-123"), Req())
    assert not ok and motivo == "locacao"


def test_rejeita_valor_mensal_disfarcado_de_total():
    ok, motivo = validar_anuncio(anuncio(preco=2_500.0, area_m2=60.0, preco_m2=41.67), Req())
    assert not ok and motivo == "preco_nao_e_total"


# ── Faixa de área ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("titulo", [
    "Apartamento para comprar com 38 - 61 m², 1 quarto",   # caso real (17.207/m²)
    "Apartamento com 40 a 65 m2",
    "Apartamento para comprar com 38 - 61 m2",
])
def test_rejeita_faixa_de_area(titulo):
    """Preço não corresponde a nenhuma das áreas — preco_m2 vira ficção."""
    ok, motivo = validar_anuncio(anuncio(nome_anuncio=titulo), Req())
    assert not ok and motivo == "faixa_de_area"


def test_aceita_area_unica_com_hifen_no_titulo():
    """Não pode confundir hífen de separação com faixa de área."""
    ok, _ = validar_anuncio(anuncio(nome_anuncio="Apartamento 60 m² - Meireles"), Req())
    assert ok


# ── Tipologia e faixa de preço ───────────────────────────────────────────────

def test_rejeita_tipologia_divergente():
    ok, motivo = validar_anuncio(anuncio(quartos=3), Req(quartos=2))
    assert not ok and motivo == "tipologia_divergente"


def test_aceita_quartos_ausente_para_imputacao_posterior():
    """Sem tipologia declarada, segue para o rf_refiner imputar."""
    ok, _ = validar_anuncio(anuncio(quartos=None), Req(quartos=2))
    assert ok


def test_rejeita_fora_da_faixa_de_preco():
    ok, motivo = validar_anuncio(anuncio(preco=900_000.0, area_m2=100.0, preco_m2=9000.0), Req())
    assert not ok and motivo == "fora_da_faixa_preco"


def test_tolera_borda_da_faixa_de_preco():
    """Os portais filtram de forma aproximada; 10% de folga evita descarte em excesso."""
    ok, _ = validar_anuncio(anuncio(preco=520_000.0, area_m2=80.0, preco_m2=6500.0), Req())
    assert ok


# ── Sanidade ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("area", [5.0, 900.0])
def test_rejeita_area_implausivel(area):
    ok, motivo = validar_anuncio(anuncio(area_m2=area, preco_m2=400_000 / area), Req())
    assert not ok and motivo in ("area_implausivel", "preco_m2_implausivel")


def test_rejeita_titulo_que_e_so_preco():
    ok, motivo = validar_anuncio(anuncio(nome_anuncio="R$ 440.000"), Req())
    assert not ok and motivo == "titulo_invalido"


def test_aceita_anuncio_valido():
    ok, motivo = validar_anuncio(anuncio(), Req(quartos=2))
    assert ok and motivo is None


# ── Agregação ────────────────────────────────────────────────────────────────

def test_filtrar_conta_motivos_de_descarte():
    itens = [
        anuncio(),
        anuncio(nome_anuncio="Apartamento para alugar"),
        anuncio(nome_anuncio="Apartamento com 38 - 61 m²"),
        anuncio(quartos=3),
    ]
    validos, descartes = filtrar_anuncios(itens, Req(quartos=2))
    assert len(validos) == 1
    assert descartes == {"locacao": 1, "faixa_de_area": 1, "tipologia_divergente": 1}
