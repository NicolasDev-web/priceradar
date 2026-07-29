"""Agente 4 — ChavesNaMão (scraping direto, sem proxy, sem Playwright).

Estratégia: httpx simples com headers de browser.
Os listings são renderizados server-side. A URL de cada imóvel encoda
área, preço e quartos no slug — parse via regex, sem precisar de JS.
URL pattern: /imovel/apartamento-a-venda-N-quartos-...-Xm2-RSY/id-Z/
"""
import asyncio
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime

import httpx

from scraper.parser import calcular_preco_m2, extrair_construtora, normalizar_cidade

logger = logging.getLogger(__name__)

CHAVESNAMAO_BASE = "https://www.chavesnamao.com.br"
MAX_PAGINAS = int(os.getenv("CHAVESNAMAO_MAX_PAGINAS", "5"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Mapa estado → sigla para construir a URL de busca
_ESTADO_URL = {
    "sp": "sp-sao-paulo", "rj": "rj-rio-de-janeiro", "mg": "mg-belo-horizonte",
    "ba": "ba-salvador", "ce": "ce-fortaleza", "pe": "pe-recife",
    "rs": "rs-porto-alegre", "pr": "pr-curitiba", "go": "go-goiania",
    "df": "df-brasilia",
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_url(cidade: str, estado: str, preco_min: float, preco_max: float, quartos: int | None, pagina: int = 1) -> str:
    cidade_slug = _sem_acento(cidade).lower().replace(" ", "-")
    estado_cidade = _ESTADO_URL.get(estado.lower(), f"{estado.lower()}-{cidade_slug}")
    url = f"{CHAVESNAMAO_BASE}/imoveis-a-venda/{estado_cidade}/?tipo=apartamento&precoMinimo={int(preco_min)}&precoMaximo={int(preco_max)}"
    if quartos:
        url += f"&quartos={quartos}"
    if pagina > 1:
        url += f"&pagina={pagina}"
    return url


def _parse_url_imovel(href: str) -> dict:
    """Extrai dados do slug da URL: área, preço, quartos, bairro, cidade."""
    dados: dict = {}

    # Área: -NNNm2-
    m = re.search(r"-(\d+)m2", href)
    if m:
        dados["area_m2"] = float(m.group(1))

    # Preço: -RSNNN/
    m = re.search(r"-RS(\d+)/", href)
    if m:
        dados["preco"] = float(m.group(1))

    # Quartos: -N-quarto
    m = re.search(r"-(\d+)-quartos?", href)
    if m:
        dados["quartos"] = int(m.group(1))

    # Slug geral: /imovel/TIPO-a-venda-...-sp-CIDADE-BAIRRO-Xm2-RSY/id-Z/
    # Tenta extrair bairro (segmento antes do m2)
    partes = href.split("/")
    slug = partes[2] if len(partes) > 2 else ""
    # Remove sufixos conhecidos e extrai bairro
    slug_clean = re.sub(r"-\d+m2.*", "", slug)
    slug_clean = re.sub(r"-RS\d+.*", "", slug_clean)
    segmentos = slug_clean.split("-")
    # Bairro costuma ser os últimos 2-3 segmentos antes do estado/cidade
    if len(segmentos) >= 4:
        dados["bairro"] = " ".join(s.capitalize() for s in segmentos[-2:])

    # ID do anúncio
    m = re.search(r"/id-(\d+)/", href)
    if m:
        dados["id_anuncio"] = m.group(1)

    return dados


def _parse_nome(href: str) -> str:
    partes = href.split("/")
    slug = partes[2] if len(partes) > 2 else ""
    slug = re.sub(r"-\d+m2.*", "", slug)
    slug = re.sub(r"-RS\d+.*", "", slug)
    slug = re.sub(r"-sp-.*", "", slug)
    slug = re.sub(r"-[a-z]{2}-", " ", slug)
    return slug.replace("-", " ").title()


async def _fetch_pagina(
    client: httpx.AsyncClient,
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    pagina: int,
    cidade_normalizada: str,
    vistos_global: set[str],
) -> list[dict]:
    target_url = _build_url(cidade, estado, preco_min, preco_max, quartos, pagina)
    try:
        resp = await client.get(target_url)
        logger.info(f"ChavesNaMão p{pagina}: status={resp.status_code} | {len(resp.content)//1024}KB")
        if resp.status_code != 200:
            return []

        html = resp.content.decode("utf-8", errors="replace")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        links = soup.select("a[href*='/imovel/']")

        resultados = []
        for link in links:
            href = link.get("href", "")
            if not href or "tipo=apartamento" in href or "/imoveis-" in href:
                continue

            dados = _parse_url_imovel(href)
            preco = dados.get("preco")
            area = dados.get("area_m2")
            id_anuncio = dados.get("id_anuncio", "")

            if not preco or not area:
                continue
            if not (preco_min <= preco <= preco_max):
                continue
            if area <= 0:
                continue
            if id_anuncio and id_anuncio in vistos_global:
                continue
            if id_anuncio:
                vistos_global.add(id_anuncio)

            if not re.search(r"apartamento|studio|flat|loft|cobertura", href, re.I):
                continue

            titulo = _parse_nome(href)
            bairro_extraido = dados.get("bairro")

            resultados.append({
                "id": str(uuid.uuid4()),
                "nome_anuncio": titulo,
                "nome_empreendimento": titulo,
                "construtora": extrair_construtora(titulo, None),
                "cidade": cidade_normalizada,
                "bairro": bairro_extraido,
                "portal": "chavesnamao",
                "preco": preco,
                "area_m2": area,
                "preco_m2": calcular_preco_m2(preco, area),
                "quartos": dados.get("quartos"),
                "banheiros": None,
                "vagas": None,
                "descricao": titulo[:300],
                "url_anuncio": CHAVESNAMAO_BASE + href,
                "data_coleta": datetime.now(),
            })

        return resultados

    except Exception as e:
        logger.error(f"ChavesNaMão p{pagina}: erro: {e}")
        return []


async def scrape_chavesnamao(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    partes = cidade.strip().split(",")
    nome_cidade = _sem_acento(partes[0].strip()).lower().replace(" ", "-")
    estado = partes[1].strip().lower() if len(partes) > 1 else "sp"
    cidade_normalizada = normalizar_cidade(partes[0].strip())

    vistos_global: set[str] = set()

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        # Busca todas as páginas em paralelo
        tarefas = [
            _fetch_pagina(client, nome_cidade, estado, preco_min, preco_max, quartos, p, cidade_normalizada, vistos_global)
            for p in range(1, MAX_PAGINAS + 1)
        ]
        paginas = await asyncio.gather(*tarefas, return_exceptions=True)

    resultados = []
    for pg in paginas:
        if isinstance(pg, list):
            resultados.extend(pg)

    logger.info(f"ChavesNaMão: {len(resultados)} anúncios encontrados ({MAX_PAGINAS} páginas)")
    return resultados
