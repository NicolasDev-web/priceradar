"""Agente 2 — ImovelWeb (scraping via Playwright, sem proxy pago).

Estratégia: Playwright renderiza a página e extrai os cards de anúncio.
Busca múltiplas páginas em paralelo para maior volume.
Padrão de URL de página 2+: apartamentos-venda-cidade-estado-pagina-N.html
"""
import asyncio
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime

from scraper.browser import buscar_html_playwright
from scraper.parser import (
    calcular_preco_m2,
    extrair_construtora,
    extrair_nome_empreendimento,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

IMOVELWEB_BASE = "https://www.imovelweb.com.br"
MAX_PAGINAS = int(os.getenv("IMOVELWEB_MAX_PAGINAS", "3"))


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_url(cidade_slug: str, estado_slug: str, preco_min: float, preco_max: float, quartos: int | None, pagina: int = 1) -> str:
    sufixo_pagina = f"-pagina-{pagina}" if pagina > 1 else ""
    base = f"{IMOVELWEB_BASE}/apartamentos-venda-{cidade_slug}-{estado_slug}{sufixo_pagina}.html"
    params = f"?precio-desde={int(preco_min)}&precio-hasta={int(preco_max)}"
    if quartos:
        params += f"&ambientes={quartos}"
    return base + params


def _limpar_preco_texto(texto: str) -> float | None:
    texto = re.sub(r"[R$\s]", "", texto).replace(".", "").replace(",", ".")
    m = re.search(r"\d[\d.]*", texto)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def _limpar_area_texto(texto: str) -> float | None:
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*m", texto.replace(",", "."))
    try:
        return float(m.group(1).replace(".", "")) if m else None
    except ValueError:
        return None


def _parse_card(card, cidade_normalizada: str, preco_min: float, preco_max: float) -> dict | None:
    """Extrai dados de um card div[data-posting-type='PROPERTY'] do ImovelWeb."""
    try:
        # Preço principal
        preco_el = card.select_one('[class*="price-container"], [class*="Price__price"]')
        if not preco_el:
            preco_el = card.select_one('[class*="price"]')
        if not preco_el:
            return None
        preco = _limpar_preco_texto(preco_el.get_text())
        if not preco or not (preco_min <= preco <= preco_max):
            return None

        # Características: "300 m² tot.  3 quartos  4 ban.  3 vagas"
        feat_spans = card.select('[class*="main-features-span"], [class*="mainFeatures"] span')
        area, quartos, banheiros, vagas = None, None, None, None
        for span in feat_spans:
            txt = span.get_text(strip=True)
            if "m²" in txt or " m" in txt:
                area = _limpar_area_texto(txt)
            elif "quarto" in txt.lower():
                m = re.search(r"\d+", txt)
                quartos = int(m.group()) if m else None
            elif "ban" in txt.lower():
                m = re.search(r"\d+", txt)
                banheiros = int(m.group()) if m else None
            elif "vaga" in txt.lower():
                m = re.search(r"\d+", txt)
                vagas = int(m.group()) if m else None

        if not area or area <= 0:
            return None

        # Localização
        bairro_el = card.select_one('[class*="location-text"], [class*="location-address"]')
        bairro = bairro_el.get_text(strip=True) if bairro_el else None

        # Link e título
        link_el = card.select_one('a[href*="propriedades"], a[data-to-posting]')
        url_rel = card.get("data-to-posting") or (link_el["href"] if link_el else "")
        url_anuncio = (IMOVELWEB_BASE + url_rel) if url_rel and not url_rel.startswith("http") else url_rel or IMOVELWEB_BASE

        titulo_el = card.select_one('[class*="title"], h2, h3')
        titulo = titulo_el.get_text(strip=True) if titulo_el else f"Apt {quartos}q {area}m²"

        descricao_el = card.select_one("a p, [class*='description']")
        descricao = descricao_el.get_text(strip=True)[:300] if descricao_el else ""

        return {
            "id": str(uuid.uuid4()),
            "nome_anuncio": titulo,
            "nome_empreendimento": extrair_nome_empreendimento(descricao),
            "construtora": extrair_construtora(titulo, descricao),
            "cidade": cidade_normalizada,
            "bairro": bairro,
            "portal": "imovelweb",
            "preco": preco,
            "area_m2": area,
            "preco_m2": calcular_preco_m2(preco, area),
            "quartos": quartos,
            "banheiros": banheiros,
            "vagas": vagas,
            "descricao": descricao,
            "url_anuncio": url_anuncio,
            "data_coleta": datetime.now(),
        }
    except Exception as e:
        logger.warning(f"ImovelWeb: erro ao parsear card: {e}")
        return None


def _parse_html_cards(html: str, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select('div[data-posting-type="PROPERTY"]')
    logger.info(f"ImovelWeb: {len(cards)} cards encontrados")
    resultados = []
    for card in cards:
        parsed = _parse_card(card, cidade_normalizada, preco_min, preco_max)
        if parsed:
            resultados.append(parsed)
    return resultados


async def _fetch_pagina_imovelweb(
    cidade_slug: str,
    estado_slug: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    pagina: int,
    cidade_normalizada: str,
) -> list[dict]:
    url = _build_url(cidade_slug, estado_slug, preco_min, preco_max, quartos, pagina)
    html = await buscar_html_playwright(
        url, f"ImovelWeb p{pagina}",
        wait_selector="[class*='listing-item'], [class*='property-card']",
    )
    if html is None:
        return []
    return _parse_html_cards(html, cidade_normalizada, preco_min, preco_max)


async def scrape_imovelweb(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    partes = cidade.strip().split(",")
    nome_cidade = _sem_acento(partes[0].strip()).lower().replace(" ", "-")
    estado_slug = partes[1].strip().lower() if len(partes) > 1 else "sp"
    cidade_normalizada = normalizar_cidade(partes[0].strip())

    tarefas = [
        _fetch_pagina_imovelweb(nome_cidade, estado_slug, preco_min, preco_max, quartos, p, cidade_normalizada)
        for p in range(1, MAX_PAGINAS + 1)
    ]
    paginas = await asyncio.gather(*tarefas, return_exceptions=True)

    # Deduplica por URL dentro do portal
    vistos: set[str] = set()
    resultados = []
    for pg in paginas:
        if not isinstance(pg, list):
            continue
        for item in pg:
            url = item.get("url_anuncio", "").split("?")[0]
            if url and url not in vistos:
                vistos.add(url)
                resultados.append(item)
            elif not url:
                resultados.append(item)

    logger.info(f"ImovelWeb: {len(resultados)} anúncios encontrados ({MAX_PAGINAS} páginas)")
    return resultados
