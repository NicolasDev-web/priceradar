"""Mede localmente quanto da coleta OLX sobrevive às regras do PriceRadar."""
import asyncio
import pathlib
import statistics
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from models import BuscaRequest
from scraper.olximoveis import scrape_olximoveis
from services.rf_refiner import refinar_com_random_forest
from services.validacao import filtrar_anuncios


async def main() -> None:
    request = BuscaRequest(
        cidade="Fortaleza, CE",
        preco_min=280_000,
        preco_max=500_000,
        quartos=2,
    )
    brutos = await scrape_olximoveis("fortaleza", "ce", request.preco_min, request.preco_max, request.quartos)
    validos, descartes = filtrar_anuncios(brutos, request)
    descartes_rf: dict[str, int] = {}
    refinados = refinar_com_random_forest(validos, descartes=descartes_rf)
    precos = [item["preco_m2"] for item in refinados]
    bairros = Counter(item.get("bairro") or "Sem bairro" for item in refinados)
    print({
        "brutos": len(brutos),
        "apos_validacao": len(validos),
        "apos_refino": len(refinados),
        "descartes_validacao": descartes,
        "descartes_refino": descartes_rf,
        "preco_m2_mediano": round(statistics.median(precos), 2) if precos else None,
        "bairros_mais_frequentes": bairros.most_common(10),
    })


if __name__ == "__main__":
    asyncio.run(main())
