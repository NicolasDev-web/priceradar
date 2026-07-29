"""
Agentes 1 e 2 — Imputação e Blindagem via Random Forest.

Pipeline:
1. Blindagem de outliers de preço de entrada: anúncios com preco_m2 abaixo de 40%
   da mediana do grupo (cidade + quartos) são removidos ANTES do RF (Agente 2).
   Também filtra títulos que são apenas um preço ("R$ 440.000"), sinal de dado
   inválido produzido pelo scraper.
2. Imputação: RandomForestRegressor preenche campos faltantes (área, quartos, vagas,
   banheiros) em vez de descartar o anúncio. Campos imputados ficam marcados em
   'campos_imputados' e causam penalidade leve no rf_score (Agente 1).
3. IsolationForest detecta anomalias de forma conservadora (contamination baixa,
   mínimo de 10 amostras antes de qualquer filtragem).
4. RandomForestRegressor prediz preco_m2 esperado para score de qualidade.
5. Filtragem por dupla confirmação: só remove se IsolationForest E RF rejeitarem.

Princípio: errar para o lado de MANTER. Anúncio válido descartado é
invisível para o usuário; anúncio ruim exibido é apenas ruído filtrável.
"""
from __future__ import annotations

import logging
import os
import re

import numpy as np

logger = logging.getLogger(__name__)

_PORTAL_IDX = {
    "vivareal": 0,
    "zapimoveis": 1,
    "mercadolivre": 2,
    "imovelweb": 3,
    "netimoveis": 4,
    "olx": 5,
    "quintoandar": 6,
    "chavesnamao": 7,
    "123imoveis": 8,
}

# Limiares conservadores
_CONTAMINATION = float(os.getenv("RF_CONTAMINATION", "0.05"))
_DESVIO_THRESHOLD = float(os.getenv("RF_DESVIO_THRESHOLD", "3.5"))
_MIN_AMOSTRAS_FILTRO = 10   # abaixo disso, não filtra nenhum anúncio
_MIN_AMOSTRAS_RF = 8        # mínimo para treinar o regressor de imputação

# Blindagem de outliers por preço relativo ao grupo (cidade + quartos).
# Banda BILATERAL: preço de entrada/parcela contamina por baixo, e anúncio
# com área agregada ou erro de parsing contamina por cima. Antes só havia
# corte inferior, e era por isso que passavam anúncios de 18.000–26.000/m².
_RATIO_MINIMO_PRECO_GRUPO = float(os.getenv("RF_RATIO_MINIMO_PRECO", "0.50"))
_RATIO_MAXIMO_PRECO_GRUPO = float(os.getenv("RF_RATIO_MAXIMO_PRECO", "1.80"))
_MIN_AMOSTRAS_GRUPO = 3     # mínimo de itens no grupo para aplicar o filtro relativo

# Regex: nome_anuncio que é só um valor monetário → sinal de dado inválido do scraper
_RE_PRECO_TITULO = re.compile(
    r'^\s*R?\$?\s*[\d.,]+\s*(mil|k|M)?\s*$',
    re.IGNORECASE,
)


# ── Agente 2: Blindagem de outliers de preço de entrada ──────────────────────

def _filtrar_preco_entrada(listings: list[dict]) -> tuple[list[dict], int]:
    """
    Remove anúncios cujo preco_m2 está fora da banda plausível do grupo.
    Dois critérios independentes:

    1. preco_m2 fora de [RATIO_MIN, RATIO_MAX] × mediana(grupo), onde
       grupo = cidade + quartos. O corte inferior pega preço de entrada/
       parcela; o superior pega área agregada e erro de parsing.
    2. nome_anuncio parece ser um preço monetário (ex.: "R$ 440.000").

    Retorna (lista filtrada, qtd removida).
    """
    remover: set[int] = set()

    # Critério 2: nome_anuncio = preço (sinal forte de scraping inválido)
    for i, l in enumerate(listings):
        nome = str(l.get("nome_anuncio") or "")
        if _RE_PRECO_TITULO.match(nome):
            remover.add(i)
            logger.debug(
                f"Outlier preço-título: idx={i} nome='{nome}' preco_m2={l.get('preco_m2')}"
            )

    # Critério 1: preço relativo ao grupo
    from collections import defaultdict
    grupos: dict[tuple, list[int]] = defaultdict(list)
    for i, l in enumerate(listings):
        cidade = str(l.get("cidade") or "").lower().strip()
        quartos = l.get("quartos") or 0
        grupos[(cidade, quartos)].append(i)

    for _chave, indices in grupos.items():
        if len(indices) < _MIN_AMOSTRAS_GRUPO:
            continue

        precos = [float(listings[i].get("preco_m2") or 0) for i in indices]
        validos = [p for p in precos if p > 0]
        if not validos:
            continue

        mediana_grupo = float(np.median(validos))
        limiar_inf = mediana_grupo * _RATIO_MINIMO_PRECO_GRUPO
        limiar_sup = mediana_grupo * _RATIO_MAXIMO_PRECO_GRUPO

        for i, preco in zip(indices, precos):
            if preco <= 0:
                continue
            if preco < limiar_inf:
                remover.add(i)
                logger.debug(
                    f"Outlier preço-relativo (baixo): idx={i} preco_m2={preco:.0f} "
                    f"< {_RATIO_MINIMO_PRECO_GRUPO:.0%} × mediana={mediana_grupo:.0f}"
                )
            elif preco > limiar_sup:
                remover.add(i)
                logger.debug(
                    f"Outlier preço-relativo (alto): idx={i} preco_m2={preco:.0f} "
                    f"> {_RATIO_MAXIMO_PRECO_GRUPO:.0%} × mediana={mediana_grupo:.0f}"
                )

    filtrados = [l for i, l in enumerate(listings) if i not in remover]
    removidos = len(remover)
    if removidos:
        logger.info(f"Blindagem outliers de entrada: removidos {removidos} anúncios")
    return filtrados, removidos


# ── Agente 1: Imputação de campos faltantes ──────────────────────────────────

def _feature_matrix(listings: list[dict]) -> np.ndarray:
    """Converte lista de dicts em matriz de features numéricas."""
    rows = []
    for l in listings:
        portal_enc = _PORTAL_IDX.get(l.get("portal", ""), 99)
        quartos = float(l.get("quartos") or 2)
        banheiros = float(l.get("banheiros") or 1)
        vagas = float(l.get("vagas") or 0)
        area = float(l.get("area_m2") or 1)
        preco = float(l.get("preco") or 0)
        preco_m2 = float(l.get("preco_m2") or (preco / area if area > 0 else 0))
        rows.append([portal_enc, quartos, banheiros, vagas, area, preco, preco_m2])
    return np.array(rows, dtype=float)


def _imputar_campos(listings: list[dict]) -> list[dict]:
    """
    Usa RandomForestRegressor para imputar campos faltantes.
    Nunca remove anúncios — apenas preenche os buracos.
    Campos imputados ficam registrados em 'campos_imputados'.
    """
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        return listings

    # ── área ────────────────────────────────────────────────────────────────
    com_area = [l for l in listings if l.get("area_m2") and float(l["area_m2"]) > 0]
    sem_area = [l for l in listings if not l.get("area_m2") or float(l.get("area_m2", 0)) <= 0]

    if sem_area and len(com_area) >= _MIN_AMOSTRAS_RF:
        def _feat_area(l):
            return [
                _PORTAL_IDX.get(l.get("portal", ""), 99),
                float(l.get("quartos") or 2),
                float(l.get("banheiros") or 1),
                float(l.get("vagas") or 0),
                float(l.get("preco") or 0),
            ]

        rf_area = RandomForestRegressor(n_estimators=50, random_state=42)
        rf_area.fit(
            np.array([_feat_area(l) for l in com_area]),
            np.array([float(l["area_m2"]) for l in com_area]),
        )
        for listing, area_pred in zip(sem_area, rf_area.predict(np.array([_feat_area(l) for l in sem_area]))):
            area_pred = max(area_pred, 20.0)
            listing["area_m2"] = round(float(area_pred), 1)
            preco = float(listing.get("preco") or 0)
            listing["preco_m2"] = round(preco / area_pred, 2) if area_pred > 0 else listing.get("preco_m2", 0)
            listing.setdefault("campos_imputados", []).append("area_m2")
            logger.debug(f"Imputação área: {listing.get('nome_anuncio')} → {listing['area_m2']}m²")

    # ── quartos ─────────────────────────────────────────────────────────────
    com_qts = [l for l in listings if l.get("quartos") is not None]
    sem_qts = [l for l in listings if l.get("quartos") is None]

    if sem_qts and len(com_qts) >= _MIN_AMOSTRAS_RF:
        def _feat_qts(l):
            return [
                _PORTAL_IDX.get(l.get("portal", ""), 99),
                float(l.get("area_m2") or 1),
                float(l.get("banheiros") or 1),
                float(l.get("vagas") or 0),
                float(l.get("preco") or 0),
            ]

        rf_qts = RandomForestRegressor(n_estimators=50, random_state=42)
        rf_qts.fit(
            np.array([_feat_qts(l) for l in com_qts]),
            np.array([float(l["quartos"]) for l in com_qts]),
        )
        for listing, qts_pred in zip(sem_qts, rf_qts.predict(np.array([_feat_qts(l) for l in sem_qts]))):
            listing["quartos"] = max(1, round(float(qts_pred)))
            listing.setdefault("campos_imputados", []).append("quartos")
            logger.debug(f"Imputação quartos: {listing.get('nome_anuncio')} → {listing['quartos']}qts")

    # ── vagas ───────────────────────────────────────────────────────────────
    com_vagas = [l for l in listings if l.get("vagas") is not None]
    sem_vagas = [l for l in listings if l.get("vagas") is None]

    if sem_vagas:
        if len(com_vagas) >= _MIN_AMOSTRAS_RF:
            def _feat_vagas(l):
                return [
                    _PORTAL_IDX.get(l.get("portal", ""), 99),
                    float(l.get("quartos") or 2),
                    float(l.get("banheiros") or 1),
                    float(l.get("area_m2") or 60),
                    float(l.get("preco") or 0),
                ]

            rf_vagas = RandomForestRegressor(n_estimators=50, random_state=42)
            rf_vagas.fit(
                np.array([_feat_vagas(l) for l in com_vagas]),
                np.array([float(l["vagas"]) for l in com_vagas]),
            )
            for listing, vagas_pred in zip(sem_vagas, rf_vagas.predict(np.array([_feat_vagas(l) for l in sem_vagas]))):
                listing["vagas"] = max(0, round(float(vagas_pred)))
                listing.setdefault("campos_imputados", []).append("vagas")
                logger.debug(f"Imputação vagas: {listing.get('nome_anuncio')} → {listing['vagas']} vagas")
        else:
            # Fallback: mediana simples
            mediana = int(round(float(np.median([float(l["vagas"]) for l in com_vagas])))) if com_vagas else 1
            for listing in sem_vagas:
                listing["vagas"] = mediana
                listing.setdefault("campos_imputados", []).append("vagas")

    # ── banheiros ───────────────────────────────────────────────────────────
    com_banh = [l for l in listings if l.get("banheiros") is not None]
    sem_banh = [l for l in listings if l.get("banheiros") is None]

    if sem_banh:
        if len(com_banh) >= _MIN_AMOSTRAS_RF:
            def _feat_banh(l):
                return [
                    _PORTAL_IDX.get(l.get("portal", ""), 99),
                    float(l.get("quartos") or 2),
                    float(l.get("vagas") or 0),
                    float(l.get("area_m2") or 60),
                    float(l.get("preco") or 0),
                ]

            rf_banh = RandomForestRegressor(n_estimators=50, random_state=42)
            rf_banh.fit(
                np.array([_feat_banh(l) for l in com_banh]),
                np.array([float(l["banheiros"]) for l in com_banh]),
            )
            for listing, banh_pred in zip(sem_banh, rf_banh.predict(np.array([_feat_banh(l) for l in sem_banh]))):
                listing["banheiros"] = max(1, round(float(banh_pred)))
                listing.setdefault("campos_imputados", []).append("banheiros")
                logger.debug(f"Imputação banheiros: {listing.get('nome_anuncio')} → {listing['banheiros']} banh")
        else:
            # Fallback: quartos - 1, mínimo 1
            for listing in sem_banh:
                listing["banheiros"] = max(1, int(listing.get("quartos") or 2) - 1)
                listing.setdefault("campos_imputados", []).append("banheiros")

    return listings


# ── Pipeline principal ────────────────────────────────────────────────────────

def refinar_com_random_forest(
    listings: list[dict],
    threshold_anomalia: float = _CONTAMINATION,
    threshold_desvio_m2: float = _DESVIO_THRESHOLD,
) -> list[dict]:
    """
    Filtra e pontua os anúncios.

    Ordem: blindagem de preço de entrada → imputação → IsolationForest → RF.
    Conservador: nunca filtra abaixo de _MIN_AMOSTRAS_FILTRO amostras.
    """
    total_entrada = len(listings)

    # ── Etapa 0: Blindagem de outliers de preço de entrada (Agente 2) ───────
    listings, removidos_entrada = _filtrar_preco_entrada(listings)

    # ── Etapa 1: Imputação de campos faltantes (Agente 1) ────────────────────
    listings = _imputar_campos(listings)

    if len(listings) < _MIN_AMOSTRAS_FILTRO:
        logger.info(
            f"RF Refiner: {len(listings)} amostras após blindagem — sem filtragem RF "
            f"(mínimo {_MIN_AMOSTRAS_FILTRO})"
        )
        for l in listings:
            l.setdefault("rf_score", 1.0)
            _aplicar_penalidade_imputacao(l)
        return listings

    try:
        from sklearn.ensemble import IsolationForest, RandomForestRegressor
    except ImportError:
        logger.warning("scikit-learn não instalado — RF Refiner desabilitado")
        for l in listings:
            l.setdefault("rf_score", 1.0)
        return listings

    X = _feature_matrix(listings)

    # ── Etapa 2: IsolationForest conservador ─────────────────────────────────
    iso = IsolationForest(
        n_estimators=100,
        contamination=threshold_anomalia,
        random_state=42,
    )
    iso.fit(X)
    anomaly_labels = iso.predict(X)
    anomaly_scores = iso.score_samples(X)

    s_min, s_max = anomaly_scores.min(), anomaly_scores.max()
    norm_scores = (
        (anomaly_scores - s_min) / (s_max - s_min)
        if s_max > s_min
        else np.ones(len(listings))
    )

    # ── Etapa 3: RandomForestRegressor para predição de preco_m2 ─────────────
    X_feat = X[:, :5]  # portal, quartos, banheiros, vagas, area_m2
    y = X[:, 6]        # preco_m2

    mask_normal = anomaly_labels == 1
    if mask_normal.sum() >= _MIN_AMOSTRAS_RF:
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_feat[mask_normal], y[mask_normal])
        y_pred = rf.predict(X_feat)
        residuos = np.abs(y - y_pred)
        desvio = residuos[mask_normal].std() or 1.0
        rf_ok = residuos <= (threshold_desvio_m2 * desvio)

        importancias = dict(zip(
            ["portal", "quartos", "banheiros", "vagas", "area_m2"],
            rf.feature_importances_,
        ))
        logger.info(f"RF feature importances: {importancias}")
    else:
        rf_ok = np.ones(len(listings), dtype=bool)
        logger.info("RF Refiner: amostras normais insuficientes para regressão — usando apenas IsolationForest")

    # ── Etapa 4: Filtragem com dupla confirmação ──────────────────────────────
    # Só remove se AMBOS IsolationForest E RF rejeitarem.
    aprovados = []
    rejeitados = 0
    for i, listing in enumerate(listings):
        iso_anomalia = anomaly_labels[i] == -1
        rf_anomalia = not rf_ok[i]

        passou = not (iso_anomalia and rf_anomalia)
        listing["rf_score"] = round(float(norm_scores[i]), 4)
        _aplicar_penalidade_imputacao(listing)

        if passou:
            aprovados.append(listing)
        else:
            rejeitados += 1
            logger.debug(
                f"RF Refiner rejeitou: {listing.get('nome_anuncio')} "
                f"preco_m2={listing.get('preco_m2')} score={listing['rf_score']:.3f}"
            )

    logger.info(
        f"RF Refiner: {total_entrada} entrada → {len(aprovados)} aprovados "
        f"({removidos_entrada} outliers entrada + {rejeitados} rejeitados RF)"
    )

    aprovados.sort(key=lambda l: (-l["rf_score"], l.get("preco_m2", 0)))
    return aprovados


def _aplicar_penalidade_imputacao(listing: dict) -> None:
    """Penaliza levemente o rf_score por campos imputados (5% por campo, máximo 20%)."""
    campos = listing.get("campos_imputados", [])
    if not campos:
        return
    penalidade = min(0.20, 0.05 * len(campos))
    listing["rf_score"] = round(max(0.0, listing.get("rf_score", 1.0) * (1 - penalidade)), 4)
