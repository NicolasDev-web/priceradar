"""Helper compartilhado: busca HTML/JSON via Playwright (browser real, sem proxy pago).

Usa headless Chromium com fingerprint realista para contornar anti-bot.
Alternativa 100% gratuita ao ScraperAPI para páginas com client-side rendering.

Funções disponíveis:
  buscar_html_playwright          — HTML após renderização (contexto efêmero)
  interceptar_api_playwright      — intercepta chamadas AJAX (contexto efêmero)
  buscar_com_contexto_persistente — contexto persistente + anti-detecção (bypass CAPTCHA)
  interceptar_api_persistente     — intercepta AJAX usando contexto persistente
"""
import logging
import os
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "25000"))
_VIEWPORT = {"width": 1366, "height": 768}
_LOCALE = "pt-BR"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Diretório onde o perfil persistente do Chrome é salvo entre execuções.
# Preserva cookies, localStorage e sessão — evita CAPTCHA na segunda visita.
_PERFIL_DIR = pathlib.Path(os.getenv("BROWSER_PROFILE_DIR", str(
    pathlib.Path.home() / ".priceradar_browser_profile"
)))

# Script injetado em todas as páginas para ocultar sinais de automação.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en']});
window.chrome = {runtime: {}};
"""


async def _novo_contexto(p):
    """Contexto efêmero simples (sem persistência de sessão)."""
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport=_VIEWPORT, locale=_LOCALE, user_agent=_UA)
    return browser, ctx


async def buscar_html_playwright(url: str, portal: str, wait_selector: str | None = None) -> str | None:
    """Abre a URL em Chromium headless e retorna o HTML completo após renderização."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright não instalado — execute: pip install playwright && playwright install chromium")
        return None

    logger.info(f"{portal} via Playwright: {url}")
    try:
        async with async_playwright() as p:
            browser, ctx = await _novo_contexto(p)
            page = await ctx.new_page()
            await page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    pass
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

            html = await page.content()
            await browser.close()

        logger.info(f"{portal} Playwright: {len(html)} bytes capturados")
        return html
    except Exception as e:
        logger.error(f"{portal} Playwright erro: {e}")
        return None


async def interceptar_api_playwright(
    url_pagina: str,
    portal: str,
    padroes_api: list[str],
    wait_selector: str | None = None,
) -> list[Any]:
    """
    Navega para url_pagina e intercepta respostas de API que contenham
    qualquer um dos padroes_api na URL. Retorna lista de JSONs capturados.

    Útil para portais que carregam listings via AJAX (ex: Netimoveis).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright não instalado")
        return []

    import asyncio as _asyncio
    logger.info(f"{portal} via Playwright (interceptar API): {url_pagina}")

    respostas: list[Any] = []

    try:
        async with async_playwright() as p:
            browser, ctx = await _novo_contexto(p)
            page = await ctx.new_page()

            async def capturar_resposta(response):
                url = response.url
                if any(p in url for p in padroes_api):
                    try:
                        data = await response.json()
                        respostas.append(data)
                        logger.info(f"{portal} interceptou: {url} → {type(data)}")
                    except Exception:
                        pass

            page.on("response", capturar_resposta)
            await page.goto(url_pagina, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=12000)
                except Exception:
                    pass
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass

            await _asyncio.sleep(2)
            await browser.close()
    except Exception as e:
        logger.error(f"{portal} Playwright interceptar erro: {e}")

    logger.info(f"{portal}: {len(respostas)} respostas de API capturadas")
    return respostas


async def buscar_com_contexto_persistente(
    url: str,
    portal: str,
    wait_selector: str | None = None,
    extra_wait_ms: int = 2000,
) -> str | None:
    """
    Abre a URL usando um perfil persistente do Chromium (salvo em disco).

    Benefícios:
    - Cookies e sessão são reutilizados entre execuções → evita CAPTCHA recorrente.
    - Injeta script stealth para ocultar sinais de automação (navigator.webdriver etc.).
    - Na primeira execução o usuário pode precisar resolver o CAPTCHA manualmente
      se headless=False for usado; nas seguintes o cookie de sessão já está salvo.

    O diretório do perfil é controlado pela env BROWSER_PROFILE_DIR
    (padrão: ~/.priceradar_browser_profile).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright não instalado")
        return None

    import asyncio as _asyncio

    _PERFIL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"{portal} via contexto persistente: {url} (perfil: {_PERFIL_DIR})")

    try:
        async with async_playwright() as p:
            # launch_persistent_context combina launch + new_context em um só:
            # salva cookies, cache, localStorage entre execuções.
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(_PERFIL_DIR),
                headless=True,
                viewport=_VIEWPORT,
                locale=_LOCALE,
                user_agent=_UA,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )

            page = await ctx.new_page()

            # Oculta sinais de automação antes de qualquer navegação
            await page.add_init_script(_STEALTH_SCRIPT)

            await page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")

            # Detecta redirecionamento para página de CAPTCHA/segurança
            titulo = await page.title()
            url_atual = page.url
            if any(t in titulo.lower() for t in ["captcha", "segurança", "security", "robot", "verificar"]):
                logger.warning(
                    f"{portal} CAPTCHA detectado! título='{titulo}' url={url_atual}\n"
                    f"  Dica: rode com headless=False uma vez para resolver manualmente.\n"
                    f"  O cookie salvo em {_PERFIL_DIR} será reutilizado nas próximas execuções."
                )
                await ctx.close()
                return None

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=12000)
                except Exception:
                    pass
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass

            if extra_wait_ms > 0:
                await _asyncio.sleep(extra_wait_ms / 1000)

            html = await page.content()
            await ctx.close()

        logger.info(f"{portal} contexto persistente: {len(html)} bytes capturados")
        return html
    except Exception as e:
        logger.error(f"{portal} contexto persistente erro: {e}")
        return None


async def interceptar_api_persistente(
    url_pagina: str,
    portal: str,
    padroes_api: list[str],
    wait_selector: str | None = None,
    extra_wait_ms: int = 3000,
) -> list[Any]:
    """
    Combina contexto persistente (anti-CAPTCHA) com interceptação de chamadas AJAX.

    Usa o mesmo perfil salvo em disco de buscar_com_contexto_persistente.
    Injeta stealth script e captura todas as respostas JSON cujas URLs
    contenham qualquer padrão de padroes_api.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright não instalado")
        return []

    import asyncio as _asyncio

    _PERFIL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"{portal} via contexto persistente (interceptar API): {url_pagina}")

    respostas: list[Any] = []

    try:
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(_PERFIL_DIR),
                headless=True,
                viewport=_VIEWPORT,
                locale=_LOCALE,
                user_agent=_UA,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )

            page = await ctx.new_page()
            await page.add_init_script(_STEALTH_SCRIPT)

            async def capturar_resposta(response):
                resp_url = response.url
                if any(pat in resp_url for pat in padroes_api):
                    try:
                        data = await response.json()
                        respostas.append({"url": resp_url, "data": data})
                        logger.info(f"{portal} interceptou: {resp_url} → {type(data)}")
                    except Exception:
                        pass

            page.on("response", capturar_resposta)

            await page.goto(url_pagina, timeout=BROWSER_TIMEOUT_MS, wait_until="domcontentloaded")

            # Detecta CAPTCHA
            titulo = await page.title()
            if any(t in titulo.lower() for t in ["captcha", "segurança", "security", "robot", "verificar"]):
                logger.warning(f"{portal} CAPTCHA detectado durante interceptação! título='{titulo}'")
                await ctx.close()
                return []

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=12000)
                except Exception:
                    pass
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass

            if extra_wait_ms > 0:
                await _asyncio.sleep(extra_wait_ms / 1000)

            await ctx.close()
    except Exception as e:
        logger.error(f"{portal} interceptar persistente erro: {e}")

    logger.info(f"{portal}: {len(respostas)} respostas de API capturadas (persistente)")
    return respostas
