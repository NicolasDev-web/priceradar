"""Agente 1 — Histórico de fontes com Random Forest para priorização.

Persiste o histórico de sucesso de cada scraper em um arquivo JSON e usa
RandomForestClassifier para prever quais fontes têm maior chance de retornar
resultados para um dado contexto (cidade, faixa de preço, quartos, hora do dia).

Enquanto não há histórico suficiente, usa ordenação por taxa de sucesso acumulada.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import tempfile
import threading
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

_HISTORICO_PATH = pathlib.Path(os.getenv(
    "HISTORICO_FONTES_PATH",
    str(pathlib.Path(__file__).parent.parent / "data" / "historico_fontes.json"),
))

# Mínimo de entradas por fonte para confiar no RF
_MIN_RF_ENTRADAS = 10

# Cada portal de cada busca reescreve o arquivo inteiro. Duas buscas simultâneas
# fariam read-modify-write no mesmo JSON e a última apagaria o que a primeira
# registrou. Mesmo cuidado que `services/bairros.py` já toma.
_LOCK_HISTORICO = threading.Lock()


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _carregar_historico() -> dict:
    if _HISTORICO_PATH.exists():
        try:
            return json.loads(_HISTORICO_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Histórico de fontes corrompido: {e}")
    return {}


def _salvar_historico(historico: dict) -> None:
    """Grava num temporário e renomeia — `os.replace` é atômico, `write_text` não.

    Sem isso, um crash no meio da escrita deixa JSON truncado; `_carregar_historico`
    engole a exceção e devolve `{}`, zerando em silêncio o histórico de todas as
    fontes — e com ele a priorização por RF.
    """
    try:
        _HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporario = tempfile.mkstemp(dir=str(_HISTORICO_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(historico, f, ensure_ascii=False, indent=2)
            os.replace(temporario, _HISTORICO_PATH)
        except Exception:
            pathlib.Path(temporario).unlink(missing_ok=True)
            raise
    except Exception as e:
        logger.warning(f"Não foi possível salvar histórico: {e}")


def registrar_resultado(portal: str, cidade: str, preco_min: float, preco_max: float, quartos: int | None, n_resultados: int) -> None:
    """Registra o resultado de uma busca no histórico persistente."""
    cidade_norm = _sem_acento(cidade.split(",")[0])
    chave = f"{portal}::{cidade_norm}"
    agora = datetime.now()

    # Ler, alterar e gravar tem que ser um bloco só: fora do lock, duas buscas
    # simultâneas leem a mesma versão e a segunda grava por cima da primeira.
    with _LOCK_HISTORICO:
        historico = _carregar_historico()

        if chave not in historico:
            historico[chave] = {"portal": portal, "cidade": cidade_norm, "entradas": []}

        historico[chave]["entradas"].append({
            "ts": agora.isoformat(),
            "preco_min": preco_min,
            "preco_max": preco_max,
            "quartos": quartos,
            "hora": agora.hour,
            "n_resultados": n_resultados,
            "teve_resultado": n_resultados > 0,
        })

        # Mantém apenas as últimas 200 entradas por fonte/cidade
        historico[chave]["entradas"] = historico[chave]["entradas"][-200:]
        _salvar_historico(historico)


def _taxa_sucesso(entradas: list[dict]) -> float:
    """Taxa simples de buscas que retornaram ao menos 1 resultado."""
    if not entradas:
        return 0.5  # prior neutro
    return sum(1 for e in entradas if e.get("teve_resultado", False)) / len(entradas)


def _featurizar(cidade: str, preco_min: float, preco_max: float, quartos: int | None) -> list[float]:
    """Features de contexto para o RF de priorização."""
    faixa_preco = (preco_max - preco_min) / max(preco_min, 1)
    hora = datetime.now().hour
    cidade_hash = float(abs(hash(_sem_acento(cidade.split(",")[0]))) % 100) / 100.0
    quartos_f = float(quartos) if quartos else 2.0
    return [faixa_preco, hora / 23.0, cidade_hash, quartos_f / 5.0]


def _treinar_rf_fontes(entradas: list[dict]):
    """Treina RF binário: contexto → tem_resultado (1/0)."""
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        return None

    X, y = [], []
    for e in entradas:
        faixa = (e.get("preco_max", 500000) - e.get("preco_min", 200000)) / max(e.get("preco_min", 200000), 1)
        hora = e.get("hora", 12)
        quartos_f = float(e.get("quartos") or 2)
        X.append([faixa, hora / 23.0, quartos_f / 5.0])
        y.append(int(e.get("teve_resultado", False)))

    arr = np.array(X)
    labels = np.array(y)
    if (labels == 0).sum() < 2 or (labels == 1).sum() < 2:
        return None

    rf = RandomForestClassifier(n_estimators=50, random_state=42, class_weight="balanced")
    rf.fit(arr, labels)
    return rf


def ordenar_fontes_por_prioridade(
    fontes: list[str],
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
) -> list[str]:
    """
    Retorna fontes reordenadas por probabilidade predita de ter resultados.
    Se não há histórico suficiente, usa taxa de sucesso simples como critério.
    """
    historico = _carregar_historico()
    cidade_norm = _sem_acento(cidade.split(",")[0])

    scores: dict[str, float] = {}
    for portal in fontes:
        chave = f"{portal}::{cidade_norm}"
        entradas = historico.get(chave, {}).get("entradas", [])

        if len(entradas) >= _MIN_RF_ENTRADAS:
            rf = _treinar_rf_fontes(entradas)
            if rf:
                try:
                    import numpy as np
                    faixa = (preco_max - preco_min) / max(preco_min, 1)
                    hora = datetime.now().hour
                    quartos_f = float(quartos or 2)
                    feat = np.array([[faixa, hora / 23.0, quartos_f / 5.0]])
                    scores[portal] = float(rf.predict_proba(feat)[0][1])
                    continue
                except Exception:
                    pass

        # Fallback: taxa de sucesso histórica ou prior neutro
        scores[portal] = _taxa_sucesso(entradas)

    ordenadas = sorted(fontes, key=lambda p: scores.get(p, 0.5), reverse=True)
    logger.info(f"Prioridade fontes: {[(p, f'{scores.get(p, 0.5):.2f}') for p in ordenadas]}")
    return ordenadas
