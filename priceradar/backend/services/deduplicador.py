"""Deduplicador cross-portal por chave de bloqueio.

O mesmo imóvel anunciado em portais diferentes tem URLs diferentes, então a
dedup por URL não o pega. Aqui comparamos os atributos.

Estratégia:
1. Agrupa os anúncios em blocos por (bairro, faixa de área, faixa de preço).
   Só pares dentro do mesmo bloco são comparados — dois imóveis que diferem
   em preço ou área não são o mesmo imóvel, então nem vale calcular.
2. Dentro do bloco, `_score_determinista` pontua o par [0,1].
3. Union-Find agrupa os pares acima do limiar; preserva um representante.

Por que não Random Forest: a versão anterior treinava um classificador cujos
rótulos eram gerados pela própria heurística que ele deveria substituir
(label 1 = preço ±3% e área ±5%), então só podia reproduzi-la. Custava duas
passadas O(n²) com SequenceMatcher — 73s para 163 anúncios — para chegar ao
mesmo resultado que a heurística direta dá em milissegundos.

Conservadorismo: errar para o lado de MANTER. Nunca descartar se a confiança
de "mesmo imóvel" for < LIMIAR_DEDUP.
"""
from __future__ import annotations

import logging
import os
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

LIMIAR_DEDUP = float(os.getenv("DEDUP_LIMIAR", "0.85"))
# Similaridade textual mínima de bairro para considerar a mesma localização.
LIMIAR_BAIRRO = float(os.getenv("DEDUP_LIMIAR_BAIRRO", "0.80"))


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _similaridade_texto(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _sem_acento(a), _sem_acento(b)).ratio()


def _features_par(a: dict, b: dict) -> list[float]:
    """Vetoriza um par de anúncios em features de similaridade para o RF."""
    preco_a = float(a.get("preco") or 0)
    preco_b = float(b.get("preco") or 0)
    area_a = float(a.get("area_m2") or 0)
    area_b = float(b.get("area_m2") or 0)
    quartos_a = a.get("quartos")
    quartos_b = b.get("quartos")

    # Diferença relativa de preço [0, ∞) → normalizada para [0, 1]
    media_preco = (preco_a + preco_b) / 2 if (preco_a + preco_b) > 0 else 1
    diff_preco_rel = abs(preco_a - preco_b) / media_preco

    # Diferença relativa de área
    media_area = (area_a + area_b) / 2 if (area_a + area_b) > 0 else 1
    diff_area_rel = abs(area_a - area_b) / media_area

    # Quartos: 1.0 se iguais, 0.0 se diferentes (None tratado como "desconhecido" → 0.5)
    if quartos_a is None or quartos_b is None:
        quartos_match = 0.5
    else:
        quartos_match = 1.0 if quartos_a == quartos_b else 0.0

    # Similaridade textual de bairro
    bairro_sim = _similaridade_texto(a.get("bairro"), b.get("bairro"))

    # Similaridade textual de nome do anúncio
    nome_sim = _similaridade_texto(a.get("nome_anuncio"), b.get("nome_anuncio"))

    # Mesmo portal (evita colapsar dois anúncios do mesmo portal que são casas diferentes)
    mesmo_portal = 1.0 if a.get("portal") == b.get("portal") else 0.0

    return [diff_preco_rel, diff_area_rel, quartos_match, bairro_sim, nome_sim, mesmo_portal]


def _score_determinista(a: dict, b: dict) -> float:
    """
    Score [0,1] de "é o mesmo imóvel".

    Preço e área parecidos NÃO bastam: numa busca já filtrada por cidade,
    tipologia e faixa de preço, dezenas de apartamentos distintos têm ~60m²
    e ~R$400k. Confiar só nisso fundia 70% dos anúncios (109 → 33 medido).

    Por isso o bairro é condição necessária: sem concordância de localização,
    o par não é o mesmo imóvel, por mais que preço e área coincidam.
    """
    diff_preco_rel, diff_area_rel, quartos_match, bairro_sim, nome_sim, mesmo_portal = _features_par(a, b)

    # Mesmo portal: o portal já deduplica internamente; anúncios distintos ali
    # são imóveis distintos.
    if mesmo_portal:
        return 0.0

    # Tipologia diferente ⇒ imóveis diferentes.
    if quartos_match == 0.0:
        return 0.0

    # Bairro é condição necessária. Ausente em um dos lados ⇒ sem evidência
    # suficiente para fundir (erra para o lado de manter).
    if bairro_sim < LIMIAR_BAIRRO:
        return 0.0

    # Preço e área precisam ser compatíveis.
    if diff_preco_rel > 0.05 or diff_area_rel > 0.08:
        return 0.0

    # A partir daqui o par é plausível; a confiança vem de quão exata é a
    # coincidência e de quanto o texto do anúncio corrobora.
    exatidao = 1.0 - (diff_preco_rel / 0.05) * 0.5 - (diff_area_rel / 0.08) * 0.3
    score = 0.60 + 0.25 * max(0.0, exatidao) + 0.15 * nome_sim

    return min(max(score, 0.0), 1.0)


def deduplicar_cross_portal(listings: list[dict]) -> list[dict]:
    """
    Remove duplicatas cross-portal mantendo o representante com mais dados.
    Nunca descarta se confiança < LIMIAR_DEDUP.

    Retorna lista com representantes únicos; duplicatas recebem campo extra
    'portais_duplicados' listando os outros portais onde aparece.
    """
    if len(listings) <= 1:
        return listings

    n = len(listings)
    # Union-Find para agrupar duplicatas
    pai = list(range(n))

    def find(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def union(x, y):
        pai[find(x)] = find(y)

    # Chave de bloqueio: só pares que caem no mesmo bloco são comparados.
    # Área em faixas de 5m² e preço em faixas de R$10k; um imóvel entra nos
    # blocos vizinhos também, para não perder pares na fronteira da faixa.
    blocos: dict[tuple, list[int]] = defaultdict(list)
    for idx, item in enumerate(listings):
        area = float(item.get("area_m2") or 0)
        preco = float(item.get("preco") or 0)
        bairro = _sem_acento(str(item.get("bairro") or ""))[:12]
        for da in (0, 1):
            for dp in (0, 1):
                blocos[(bairro, int(area // 5) + da, int(preco // 10_000) + dp)].append(idx)

    pares_avaliados = 0
    ja_comparados: set[tuple[int, int]] = set()
    for indices in blocos.values():
        if len(indices) < 2:
            continue
        for pos_i, i in enumerate(indices):
            for j in indices[pos_i + 1:]:
                par = (i, j) if i < j else (j, i)
                if par in ja_comparados:
                    continue
                ja_comparados.add(par)

                pares_avaliados += 1
                if _score_determinista(listings[i], listings[j]) >= LIMIAR_DEDUP:
                    union(i, j)

    logger.info(
        f"Dedup: {pares_avaliados} pares avaliados em {len(blocos)} blocos "
        f"(de {n*(n-1)//2} pares possíveis), limiar={LIMIAR_DEDUP}"
    )

    # Agrupa por cluster
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        raiz = find(i)
        clusters.setdefault(raiz, []).append(i)

    # Escolhe o representante com mais campos preenchidos
    def _completude(idx: int) -> int:
        item = listings[idx]
        return sum(1 for v in item.values() if v is not None and v != "")

    resultado = []
    for raiz, indices in clusters.items():
        rep_idx = max(indices, key=_completude)
        rep = listings[rep_idx].copy()

        outros_portais = [
            listings[i]["portal"] for i in indices if i != rep_idx
        ]
        if outros_portais:
            rep["portais_duplicados"] = outros_portais

        resultado.append(rep)

    descartados = n - len(resultado)
    logger.info(f"Dedup: {n} entradas → {len(resultado)} únicos ({descartados} duplicatas removidas)")
    return resultado
