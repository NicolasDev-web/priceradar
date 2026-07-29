"""Camada de acesso HTTP com escalonamento progressivo.

Ordem de tentativa, do mais barato para o mais caro:

    1. curl-cffi (TLS impersonation)  →  grátis, ~1s
    2. ScraperAPI (proxy rotativo)    →  1 crédito, ~5-25s
    3. Playwright (browser real)      →  grátis, ~15-25s, fica a cargo do scraper

Por que o nível 1 funciona: VivaReal, Zap, ImovelWeb e OLX não bloqueiam por
User-Agent — bloqueiam pela assinatura TLS/JA3 do cliente. httpx tem uma
assinatura de biblioteca Python, reconhecível na hora; curl-cffi replica a
assinatura de um Chrome real e os mesmos portais que devolviam 403 passam a
devolver 200 (medido em 29/07/2026: vivareal 403→200 em 1,1s, zap 403→200 em
0,8s, olx 403→200).

Isso importa porque o plano gratuito da ScraperAPI tem 1.000 créditos/mês.
Com o nível 1 resolvendo a maior parte das requisições, a cota deixa de ser o
limite de quantas buscas o time comercial pode fazer.
"""
import asyncio
import logging
import os
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
SCRAPERAPI_URL = "https://api.scraperapi.com/"

TIMEOUT_SEGUNDOS = float(os.getenv("SCRAPER_TIMEOUT", "30"))
MAX_TENTATIVAS = 2

# Perfil de browser que o curl-cffi imita. chrome131 foi o que passou em
# todos os portais testados; safari17_0 falha no ImovelWeb.
IMPERSONATE = os.getenv("CURL_IMPERSONATE", "chrome131")

# Permite desligar cada nível sem mexer no código.
DIRETO_HABILITADO = os.getenv("HABILITAR_FETCH_DIRETO", "true").lower() == "true"
SCRAPERAPI_HABILITADO = os.getenv("HABILITAR_SCRAPERAPI", "true").lower() == "true"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


async def buscar_html_direto(target_url: str, portal: str) -> str | None:
    """
    Nível 1: requisição direta com assinatura TLS de Chrome real.

    curl-cffi é síncrono, então roda numa thread para não bloquear o event loop
    (os scrapers disparam várias páginas em paralelo via asyncio.gather).
    """
    try:
        from curl_cffi import requests as cr
    except ImportError:
        logger.debug("curl-cffi não instalado — pulando fetch direto")
        return None

    def _get() -> tuple[int, str]:
        resp = cr.get(
            target_url,
            impersonate=IMPERSONATE,
            timeout=TIMEOUT_SEGUNDOS,
            headers=_HEADERS,
        )
        return resp.status_code, resp.text

    try:
        status, html = await asyncio.to_thread(_get)
    except Exception as e:
        logger.info(f"{portal}: fetch direto falhou ({type(e).__name__}: {str(e)[:80]})")
        return None

    if status == 200 and html:
        logger.info(f"{portal}: direto OK | {len(html) // 1024}KB")
        return html

    logger.info(f"{portal}: direto retornou {status} — escalando")
    return None


async def buscar_html_scraperapi(target_url: str, portal: str) -> str | None:
    """
    Nível 2: ScraperAPI. Consome 1 crédito por requisição.

    render=false porque os dados vêm no HTML inicial (JSON-LD) — renderizar JS
    multiplicaria o custo e o tempo sem trazer nada.
    """
    if not SCRAPERAPI_KEY:
        logger.warning(f"{portal}: SCRAPERAPI_KEY não configurada")
        return None

    params = urlencode({
        "api_key": SCRAPERAPI_KEY,
        "url": target_url,
        "render": "false",
        "country_code": "br",
    })
    proxy_url = f"{SCRAPERAPI_URL}?{params}"

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
                resp = await client.get(proxy_url)

            if resp.status_code == 200:
                logger.info(f"{portal}: ScraperAPI OK | {len(resp.content) // 1024}KB (1 crédito)")
                return resp.content.decode("utf-8", errors="replace")

            # 5xx da ScraperAPI são transitórios — vale uma nova tentativa
            if resp.status_code >= 500 and tentativa < MAX_TENTATIVAS:
                logger.warning(f"{portal}: ScraperAPI {resp.status_code} transitório, retentando")
                continue

            logger.warning(f"{portal}: ScraperAPI retornou {resp.status_code}, desistindo")
            return None

        except httpx.TimeoutException:
            logger.warning(f"{portal}: ScraperAPI timeout na tentativa {tentativa}")
            if tentativa >= MAX_TENTATIVAS:
                return None
        except Exception as e:
            logger.error(f"{portal}: ScraperAPI erro: {e}")
            return None

    return None


async def buscar_html(target_url: str, portal: str) -> str | None:
    """
    Busca o HTML escalando do mais barato para o mais caro.

    Devolve None se todos os níveis falharem — cabe ao scraper decidir se vale
    tentar Playwright (nível 3), que é caro em tempo e só compensa em portais
    que dependem de renderização de JS.
    """
    if DIRETO_HABILITADO:
        html = await buscar_html_direto(target_url, portal)
        if html is not None:
            return html

    if SCRAPERAPI_HABILITADO:
        return await buscar_html_scraperapi(target_url, portal)

    return None


def montar_url_scraperapi(target_url: str) -> str:
    """Mantido para compatibilidade com chamadas antigas."""
    params = urlencode({
        "api_key": SCRAPERAPI_KEY,
        "url": target_url,
        "render": "false",
        "country_code": "br",
    })
    return f"{SCRAPERAPI_URL}?{params}"
