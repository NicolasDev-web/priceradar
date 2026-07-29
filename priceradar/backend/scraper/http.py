"""Helpers compartilhados para requisições via ScraperAPI."""
import logging
import os
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
SCRAPERAPI_URL = "https://api.scraperapi.com/"

# Timeout curto: os dados vêm no JSON-LD do HTML inicial (render=false ≈ 2-5s).
# Se a ScraperAPI travar (erros 500 intermitentes), não esperamos 55s à toa.
TIMEOUT_SEGUNDOS = float(os.getenv("SCRAPER_TIMEOUT", "25"))
MAX_TENTATIVAS = 2


def montar_url_scraperapi(target_url: str) -> str:
    """Monta a URL do proxy ScraperAPI. render=false pois lemos o JSON-LD do HTML."""
    params = urlencode({
        "api_key": SCRAPERAPI_KEY,
        "url": target_url,
        "render": "false",
        "country_code": "br",
    })
    return f"{SCRAPERAPI_URL}?{params}"


async def buscar_html(target_url: str, portal: str) -> str | None:
    """
    Busca o HTML via ScraperAPI com retry rápido em erros transitórios (5xx).
    Retorna o HTML decodificado em UTF-8, ou None em caso de falha.
    """
    if not SCRAPERAPI_KEY:
        logger.error(f"{portal}: SCRAPERAPI_KEY não configurada")
        return None

    proxy_url = montar_url_scraperapi(target_url)
    logger.info(f"{portal} via ScraperAPI: {target_url}")

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
                resp = await client.get(proxy_url)

            logger.info(f"{portal} status: {resp.status_code} | {len(resp.content)} bytes (tentativa {tentativa})")

            if resp.status_code == 200:
                return resp.content.decode("utf-8", errors="replace")

            # 5xx da ScraperAPI são transitórios — vale uma nova tentativa
            if resp.status_code >= 500 and tentativa < MAX_TENTATIVAS:
                logger.warning(f"{portal}: {resp.status_code} transitório, tentando novamente")
                continue

            logger.warning(f"{portal}: retornou {resp.status_code}, desistindo")
            return None

        except httpx.TimeoutException:
            logger.warning(f"{portal}: timeout na tentativa {tentativa}")
            if tentativa >= MAX_TENTATIVAS:
                return None
        except Exception as e:
            logger.error(f"{portal}: erro na requisição: {e}")
            return None

    return None
