"""Avalia o agrupamento por empreendimento sobre o histórico gravado.

Lê o banco em modo SOMENTE LEITURA, pega a observação mais recente de cada
anúncio (URL normalizada) de uma cidade, roda `services.agrupamento.agrupar`
e imprime:

- quantos grupos saíram, a distribuição de tamanhos e o sinal que uniu;
- N grupos sorteados com endereço, áreas, quartos e preço/m² de cada membro,
  para conferência à mão — a pergunta é "isto é um prédio só?".

Uso (de dentro de backend/):
    venv/Scripts/python scripts/avaliar_agrupamento.py --cidade fortaleza --amostra 30
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.parser import revisar_empreendimento_gravado  # noqa: E402
from scraper.rsc_grupozap import chave_url  # noqa: E402
from services.agrupamento import agrupar, mediana_por_empreendimento  # noqa: E402
from services.texto import normalizar  # noqa: E402

_COLUNAS = (
    'url_anuncio', 'nome_anuncio', 'nome_empreendimento', 'descricao', 'cidade', 'bairro',
    'endereco', 'latitude', 'longitude', 'origem_coordenada', 'portal', 'preco', 'area_m2',
    'preco_m2', 'quartos', 'data_coleta',
)


def carregar(banco: Path, cidade: str, desde: str | None = None) -> list[dict]:
    con = sqlite3.connect(f'file:{banco.as_posix()}?mode=ro', uri=True)
    filtro = " and data_coleta >= ?" if desde else ""
    linhas = con.execute(f"select {', '.join(_COLUNAS)} from empreendimentos where preco_m2 > 0{filtro}",
                         (desde,) if desde else ()).fetchall()
    con.close()

    alvo = normalizar(cidade)
    mais_recente: dict[str, dict] = {}
    for linha in linhas:
        item = dict(zip(_COLUNAS, linha))
        if normalizar(item['cidade'] or '') != alvo:
            continue
        chave = chave_url(item['url_anuncio']) or item['url_anuncio']
        atual = mais_recente.get(chave)
        if atual is None or (item['data_coleta'] or '') > (atual['data_coleta'] or ''):
            mais_recente[chave] = item
    itens = list(mais_recente.values())
    # Mesma revisão que o cache e o dossiê fazem no que vem do banco.
    for item in itens:
        revisar_empreendimento_gravado(item)
    return itens


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--banco', default='priceradar.db')
    ap.add_argument('--cidade', default='fortaleza')
    ap.add_argument('--amostra', type=int, default=30)
    ap.add_argument('--semente', type=int, default=42)
    # As linhas de antes de 15/10/2026 não têm número de porta: para avaliar a
    # aba "mesmo prédio", restrinja às coletas recentes (ex.: --desde 2026-10-15).
    ap.add_argument('--desde', default=None, help='só anúncios coletados a partir desta data (AAAA-MM-DD)')
    ap.add_argument('--nivel', default=None, choices=['mesmo_predio', 'mesmo_local', 'mesmo_nome'],
                    help='amostra só deste nível')
    args = ap.parse_args()

    itens = carregar(Path(args.banco), args.cidade, args.desde)
    grupos = agrupar(itens)
    agrupados = sum(g['n_anuncios'] for g in grupos)

    print(f'Anúncios distintos: {len(itens)} | agrupados: {agrupados} ({agrupados / max(len(itens), 1):.0%})')
    print(f'Grupos: {len(grupos)}')
    print('Tamanho (anúncios):', sorted(Counter(min(g["n_anuncios"], 20) for g in grupos).items()))
    print('Sinais:', Counter('+'.join(g['sinais']) for g in grupos).most_common())
    print('Confiança:', Counter(g['confianca'] for g in grupos).most_common())
    for nivel in ('mesmo_predio', 'mesmo_local', 'mesmo_nome'):
        gs = [g for g in grupos if g['nivel'] == nivel]
        if not gs:
            print(f'  {nivel:<13} 0 grupos')
            continue
        razoes = [g['preco_m2_max'] / g['preco_m2_min'] for g in gs]
        print(f"  {nivel:<13} {len(gs):>4} grupos | {sum(g['n_anuncios'] for g in gs):>5} anúncios | "
              f"{sum(g['n_provaveis'] for g in gs):>3} prováveis | dispersão max/min ≤1,3 em "
              f"{sum(r <= 1.3 for r in razoes) / len(razoes):.0%}")
    print('Com nome:', sum(1 for g in grupos if g['nome']), '| lançamento:', sum(1 for g in grupos if g['eh_lancamento']))
    precos = sorted(float(i['preco_m2']) for i in itens)
    print(f'Mediana por anúncio: {precos[len(precos) // 2]:.0f} | '
          f'por empreendimento: {mediana_por_empreendimento(itens, grupos):.0f}')

    por_id = {}
    for item in itens:
        if item['grupo_id']:
            por_id.setdefault(item['grupo_id'], []).append(item)

    random.seed(args.semente)
    pool = [g for g in grupos if not args.nivel or g['nivel'] == args.nivel]
    for g in random.sample(pool, min(args.amostra, len(pool))):
        print(f"\n== [{g['nivel']}] {g['nome'] or g['endereco'] or '?'} | {g['bairro']} | {g['n_anuncios']} anúncios / "
              f"{g['n_unidades']} unidades | mediana {g['preco_m2_mediana']:.0f}/m² | {g['sinais']}")
        for m in sorted(por_id[g['grupo_id']], key=lambda i: (i['area_m2'], i['preco'])):
            marca = '?' if m['vinculo_grupo'] == 'provavel' else ' '
            print(f" {marca} {m['portal']:<11} {m['area_m2']:>6.0f} m² {m['quartos'] or '?'}q "
                  f"{m['preco_m2']:>7.0f}/m²  {str(m['endereco'] or '')[:32]:<32} {str(m['nome_anuncio'])[:50]}")


if __name__ == '__main__':
    main()
