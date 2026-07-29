"""Testes da busca por vários bairros.

Motivo do comparativo: numa busca real em Fortaleza, Meireles deu R$9.321/m² e
Messejana R$6.382/m² — 46% de diferença. A mediana consolidada foi R$7.653/m²,
um número que não descreve nenhum dos dois bairros e esconde exatamente a
comparação que a análise procura.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import BuscaRequest  # noqa: E402
from repositories.busca_repo import _chave_bairros  # noqa: E402
from services.search import _resumir_por_bairro  # noqa: E402


def req(**kw):
    base = dict(cidade="Fortaleza, CE", preco_min=280_000, preco_max=500_000)
    base.update(kw)
    return BuscaRequest(**base)


# ── Normalização da entrada ──────────────────────────────────────────────────

def test_aceita_lista_de_bairros():
    assert req(bairros=["Aldeota", "Meireles"]).lista_bairros == ["Aldeota", "Meireles"]


def test_campo_bairro_antigo_continua_valendo():
    """Histórico e cache já gravados usam `bairro` no singular."""
    assert req(bairro="Aldeota").lista_bairros == ["Aldeota"]


def test_combina_os_dois_campos_sem_duplicar():
    """A comparação ignora caixa, e a primeira grafia digitada é a que fica."""
    r = req(bairro="Aldeota", bairros=["Meireles", "aldeota"])
    assert r.lista_bairros == ["Meireles", "aldeota"]


@pytest.mark.parametrize("entrada", [None, [], ["", "   "]])
def test_sem_bairro_devolve_lista_vazia(entrada):
    assert req(bairros=entrada).lista_bairros == []


# ── Chave de cache ───────────────────────────────────────────────────────────

def test_chave_de_cache_independe_da_ordem():
    """"Aldeota, Meireles" e "Meireles, Aldeota" são a mesma pergunta."""
    a = _chave_bairros(req(bairros=["Aldeota", "Meireles"]))
    b = _chave_bairros(req(bairros=["Meireles", "Aldeota"]))
    assert a == b == "aldeota,meireles"


def test_chave_de_cache_sem_bairro_e_nula():
    assert _chave_bairros(req()) is None


# ── Resumo por bairro ────────────────────────────────────────────────────────

class Emp:
    """Stub com só o que o resumo lê."""
    def __init__(self, bairro, preco_m2):
        self.bairro = bairro
        self.preco_m2 = preco_m2


def test_resumo_agrupa_e_ordena_por_mediana():
    emps = [
        Emp("Meireles", 9000), Emp("Meireles", 9500), Emp("Meireles", 10000),
        Emp("Messejana", 6000), Emp("Messejana", 6400), Emp("Messejana", 6800),
    ]
    resumo = _resumir_por_bairro(emps, ["Messejana", "Meireles"])
    assert [r.bairro for r in resumo] == ["Meireles", "Messejana"]  # mais caro primeiro
    assert resumo[0].preco_m2_mediana == 9500
    assert resumo[1].preco_m2_mediana == 6400
    assert resumo[0].total == 3


def test_resumo_so_existe_com_dois_ou_mais_bairros():
    """Com um bairro só, o resumo repetiria o KPI principal."""
    assert _resumir_por_bairro([Emp("Aldeota", 7000)], ["Aldeota"]) == []


def test_bairro_pedido_sem_resultado_fica_de_fora():
    """Linha zerada não informa nada que o total já não diga."""
    emps = [Emp("Aldeota", 7000), Emp("Aldeota", 7500)]
    resumo = _resumir_por_bairro(emps, ["Aldeota", "Bairro Inexistente"])
    assert [r.bairro for r in resumo] == ["Aldeota"]


def test_resumo_ignora_anuncio_de_outro_bairro():
    emps = [Emp("Aldeota", 7000), Emp("Centro", 4000), Emp("Meireles", 9000)]
    resumo = _resumir_por_bairro(emps, ["Aldeota", "Meireles"])
    assert sum(r.total for r in resumo) == 2


def test_comparacao_ignora_acento_e_caixa():
    emps = [Emp("São João do Tauape", 5000), Emp("São João do Tauape", 5500)]
    resumo = _resumir_por_bairro(emps, ["sao joao do tauape", "Aldeota"])
    assert resumo and resumo[0].total == 2
