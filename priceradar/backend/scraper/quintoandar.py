"""Agente 5 — QuintoAndar (scraping via __NEXT_DATA__, sem proxy, sem Playwright).

Estratégia: httpx direto com headers de browser. O QuintoAndar renderiza
server-side e embute o estado inicial (incl. listings) em __NEXT_DATA__.
Estrutura: props.pageProps.initialState.houses[ID] → dados do imóvel
           props.pageProps.initialState.search.visibleHouses.pages[0] → IDs visíveis
"""
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime

import httpx

from scraper.parser import calcular_preco_m2, normalizar_cidade
from services.texto import sem_acento

logger = logging.getLogger(__name__)

QA_BASE = "https://www.quintoandar.com.br"
QA_IMOVEL = "https://www.quintoandar.com.br/imovel"
MAX_PAGINAS_QA = int(os.getenv("QUINTOANDAR_MAX_PAGINAS", "3"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

_CIDADE_SLUG = {
    "sao paulo": "sao-paulo-sp-brasil",
    "são paulo": "sao-paulo-sp-brasil",
    "rio de janeiro": "rio-de-janeiro-rj-brasil",
    "belo horizonte": "belo-horizonte-mg-brasil",
    "curitiba": "curitiba-pr-brasil",
    "porto alegre": "porto-alegre-rs-brasil",
    "fortaleza": "fortaleza-ce-brasil",
    "salvador": "salvador-ba-brasil",
    "recife": "recife-pe-brasil",
    "goiania": "goiania-go-brasil",
    "goiânia": "goiania-go-brasil",
    "brasilia": "brasilia-df-brasil",
    "brasília": "brasilia-df-brasil",
}


def _cidade_para_slug(cidade: str, estado: str) -> str:
    chave = sem_acento(cidade).lower().strip()
    if chave in _CIDADE_SLUG:
        return _CIDADE_SLUG[chave]
    return f"{chave.replace(' ', '-')}-{estado.lower()}-brasil"


def _extrair_next_data(html: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _parse_house(house: dict, cidade_normalizada: str, preco_min: float, preco_max: float) -> dict | None:
    """Converte um dict de house do QuintoAndar para o formato Empreendimento."""
    try:
        if not house.get("forSale"):
            return None
        if house.get("type", "").lower() not in ("apartamento", "studio", "flat", "cobertura", "loft"):
            return None

        preco = float(house.get("salePrice") or 0)
        area = float(house.get("area") or 0)
        if preco <= 0 or area <= 0:
            return None
        if not (preco_min <= preco <= preco_max):
            return None

        quartos = house.get("bedrooms")
        banheiros = house.get("bathrooms")
        vagas = house.get("parkingSpots")
        bairro = house.get("neighbourhood") or house.get("regionName")
        endereco = house.get("address", {}).get("address", "")
        tipo = house.get("type", "Apartamento")
        house_id = str(house.get("id", ""))
        nome = f"{tipo} {quartos}q {int(area)}m² - {bairro}" if bairro else f"{tipo} {int(area)}m²"

        return {
            "id": str(uuid.uuid4()),
            "nome_anuncio": nome,
            "nome_empreendimento": nome,
            "construtora": None,
            "cidade": cidade_normalizada,
            "bairro": bairro,
            "portal": "quintoandar",
            "preco": preco,
            "area_m2": area,
            "preco_m2": calcular_preco_m2(preco, area),
            "quartos": int(quartos) if quartos else None,
            "banheiros": int(banheiros) if banheiros else None,
            "vagas": int(vagas) if vagas else None,
            "descricao": f"{endereco} — {bairro}" if endereco else bairro or "",
            "url_anuncio": f"{QA_IMOVEL}/{house_id}",
            "data_coleta": datetime.now(),
        }
    except Exception as e:
        logger.warning(f"QuintoAndar: erro ao parsear house: {e}")
        return None


async def _fetch_pagina_qa(
    client: httpx.AsyncClient,
    url: str,
    cidade_normalizada: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    vistos: set[str],
) -> list[dict]:
    """Busca uma página do QuintoAndar e retorna os anúncios parseados."""
    try:
        resp = await client.get(url)
        logger.info(f"QuintoAndar {url}: status={resp.status_code} | {len(resp.content)//1024}KB")
        if resp.status_code != 200:
            return []

        html = resp.content.decode("utf-8", errors="replace")
        nd = _extrair_next_data(html)
        if not nd:
            return []

        init = nd.get("props", {}).get("pageProps", {}).get("initialState", {})
        houses = init.get("houses", {})
        search = init.get("search", {})

        visible_pages = search.get("visibleHouses", {}).get("pages", {})
        visible_ids: list[str] = []
        if isinstance(visible_pages, dict):
            for page_ids in visible_pages.values():
                if isinstance(page_ids, list):
                    visible_ids.extend(str(i) for i in page_ids)

        if not visible_ids:
            visible_ids = list(houses.keys())

        resultados = []
        for house_id in visible_ids:
            if house_id in vistos:
                continue
            vistos.add(house_id)
            house = houses.get(str(house_id))
            if not house or not isinstance(house, dict):
                continue
            parsed = _parse_house(house, cidade_normalizada, preco_min, preco_max)
            if parsed:
                if quartos and parsed.get("quartos") and parsed["quartos"] != quartos:
                    continue
                resultados.append(parsed)

        return resultados

    except Exception as e:
        logger.error(f"QuintoAndar {url}: erro: {e}")
        return []


async def scrape_quintoandar(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    partes = cidade.strip().split(",")
    nome_cidade = sem_acento(partes[0].strip())
    estado = partes[1].strip().lower() if len(partes) > 1 else "sp"
    cidade_normalizada = normalizar_cidade(partes[0].strip())
    slug = _cidade_para_slug(nome_cidade, estado)

    base_url = f"{QA_BASE}/comprar/imovel/{slug}"
    urls = [base_url] + [f"{base_url}?pagina={p}" for p in range(2, MAX_PAGINAS_QA + 1)]

    vistos: set[str] = set()
    async with httpx.AsyncClient(headers=_HEADERS, timeout=25, follow_redirects=True) as client:
        tarefas = [_fetch_pagina_qa(client, u, cidade_normalizada, preco_min, preco_max, quartos, vistos) for u in urls]
        paginas = await asyncio.gather(*tarefas, return_exceptions=True)

    resultados = []
    for pg in paginas:
        if isinstance(pg, list):
            resultados.extend(pg)

    logger.info(f"QuintoAndar: {len(resultados)} anúncios encontrados ({MAX_PAGINAS_QA} páginas)")
    return resultados
