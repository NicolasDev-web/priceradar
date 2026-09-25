"""Compara uma busca com a última busca igual — selos "Novo", "preço caiu/subiu"
e o resumo "desde a última busca" (alertas no app).

O mesmo anúncio é reconhecido pela URL (decisão de 25/09/2026): é exato — o
mesmo anúncio no mesmo portal. Não junta o mesmo prédio anunciado por
imobiliárias diferentes; isso é trabalho do deduplicador.
"""
from __future__ import annotations

from database.models_db import BuscaSalva
from models import BuscaResponse, ComparacaoBusca
from scraper.rsc_grupozap import chave_url

# Abaixo disso é arredondamento do portal, não mudança de preço.
VARIACAO_MINIMA = 0.005


def comparar_com_anterior(resultado: BuscaResponse, anterior: BuscaSalva | None) -> None:
    """Preenche os campos de comparação em `resultado`, no lugar."""
    if anterior is None or not anterior.empreendimentos:
        return

    antes = {chave_url(e.url_anuncio): e for e in anterior.empreendimentos if e.url_anuncio}
    vistos: set[str] = set()
    novos = baixaram = subiram = 0

    for emp in resultado.empreendimentos:
        chave = chave_url(emp.url_anuncio)
        vistos.add(chave)
        velho = antes.get(chave)
        if velho is None:
            emp.novo = True
            novos += 1
            continue
        if velho.preco and abs(emp.preco - velho.preco) / velho.preco > VARIACAO_MINIMA:
            emp.preco_anterior = velho.preco
            emp.data_preco_anterior = anterior.criado_em
            if emp.preco < velho.preco:
                baixaram += 1
            else:
                subiram += 1

    portais_ok = {e.portal for e in resultado.empreendimentos}
    sairam = sum(1 for k, e in antes.items() if k not in vistos and e.portal in portais_ok)

    resultado.comparacao = ComparacaoBusca(
        data_anterior=anterior.criado_em, novos=novos, baixaram=baixaram, subiram=subiram, sairam=sairam,
    )
