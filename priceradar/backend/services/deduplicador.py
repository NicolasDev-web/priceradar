"""Agente 2 — Deduplicador cross-portal com Random Forest.

Estratégia:
1. Para cada par de anúncios (A, B), calcula features de similaridade.
2. Treina RandomForestClassifier auto-supervisionado:
   - Pares "obviamente iguais" (mesma área, preço, quartos, mesmo bairro) → label 1
   - Pares "obviamente diferentes" (área ou preço muito distante) → label 0
3. O RF prediz a probabilidade de cada par ser o mesmo imóvel.
4. Agrupa os anúncios em clusters; preserva um representante por cluster.

Conservadorismo: errar para o lado de MANTER, nunca descartar
se a confiança de "mesmo imóvel" for < LIMIAR_DEDUP.
"""
from __future__ import annotations

import logging
import unicodedata
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

LIMIAR_DEDUP = float(__import__("os").getenv("DEDUP_LIMIAR", "0.85"))
MIN_AMOSTRAS_RF = 20  # mínimo de pares para treinar o RF


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
    """Score heurístico [0,1] de 'mesmo imóvel' sem ML (usado quando RF não tem dados)."""
    feat = _features_par(a, b)
    diff_preco_rel, diff_area_rel, quartos_match, bairro_sim, nome_sim, mesmo_portal = feat

    # Critério forte: preço e área muito próximos + mesmo bairro
    if diff_preco_rel < 0.03 and diff_area_rel < 0.05:
        base = 0.90
    elif diff_preco_rel < 0.08 and diff_area_rel < 0.10:
        base = 0.70
    elif diff_preco_rel < 0.15 and diff_area_rel < 0.15:
        base = 0.50
    else:
        base = 0.10

    # Ajustes por features complementares
    base += (quartos_match - 0.5) * 0.15
    base += bairro_sim * 0.10
    base += nome_sim * 0.05

    # Penaliza pares do mesmo portal (menos provável que o mesmo imóvel esteja duplicado no mesmo portal)
    if mesmo_portal:
        base *= 0.5

    return min(max(base, 0.0), 1.0)


def _gerar_pares_treino(listings: list[dict]) -> tuple[list[list[float]], list[int]]:
    """
    Gera pares de treino auto-supervisionados:
    - Label 1 (mesmo imóvel): pares com preço ±3%, área ±5%, mesmo bairro, portais diferentes
    - Label 0 (imóveis diferentes): pares com preço ou área muito distantes
    """
    X, y = [], []
    n = len(listings)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = listings[i], listings[j]
            feat = _features_par(a, b)
            diff_preco_rel, diff_area_rel, quartos_match, bairro_sim, _, mesmo_portal = feat

            if diff_preco_rel < 0.03 and diff_area_rel < 0.05 and quartos_match >= 0.5 and not mesmo_portal:
                X.append(feat)
                y.append(1)
            elif diff_preco_rel > 0.30 or diff_area_rel > 0.30:
                X.append(feat)
                y.append(0)

    return X, y


def _treinar_rf(X: list[list[float]], y: list[int]):
    """Treina RF de pares se houver amostras suficientes de ambas as classes."""
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        return None

    arr = np.array(X)
    labels = np.array(y)
    if (labels == 0).sum() < 3 or (labels == 1).sum() < 3:
        return None

    rf = RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced")
    rf.fit(arr, labels)
    logger.info(
        f"Dedup RF: treinado com {len(y)} pares ({(labels==1).sum()} positivos, {(labels==0).sum()} negativos)"
    )
    return rf


def _score_rf(rf, a: dict, b: dict) -> float:
    """Usa RF para predizer probabilidade de 'mesmo imóvel'."""
    try:
        import numpy as np
        feat = np.array([_features_par(a, b)])
        return float(rf.predict_proba(feat)[0][1])
    except Exception:
        return _score_determinista(a, b)


def deduplicar_cross_portal(listings: list[dict]) -> list[dict]:
    """
    Remove duplicatas cross-portal mantendo o representante com mais dados.
    Nunca descarta se confiança < LIMIAR_DEDUP.

    Retorna lista com representantes únicos; duplicatas recebem campo extra
    'portais_duplicados' listando os outros portais onde aparece.
    """
    if len(listings) <= 1:
        return listings

    # Tenta treinar RF com os pares gerados automaticamente
    rf = None
    if len(listings) >= 5:
        X, y = _gerar_pares_treino(listings)
        if len(X) >= MIN_AMOSTRAS_RF:
            rf = _treinar_rf(X, y)

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

    pares_avaliados = 0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = listings[i], listings[j]

            # Não faz dedup dentro do mesmo portal (improvável ser o mesmo imóvel)
            if a.get("portal") == b.get("portal"):
                continue

            # Score rápido (evita RF para pares obviamente diferentes)
            diff_preco = abs((a.get("preco") or 0) - (b.get("preco") or 0))
            media_p = ((a.get("preco") or 0) + (b.get("preco") or 0)) / 2 or 1
            if diff_preco / media_p > 0.25:
                continue

            score = _score_rf(rf, a, b) if rf else _score_determinista(a, b)
            pares_avaliados += 1

            if score >= LIMIAR_DEDUP:
                union(i, j)

    logger.info(f"Dedup: {pares_avaliados} pares avaliados, limiar={LIMIAR_DEDUP}")

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
