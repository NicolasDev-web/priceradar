"""ChavesNaMão — scraping direto, sem proxy pago e sem Playwright.

Estratégia: httpx com headers de browser + leitura do JSON-LD embutido.
O bloco `RealEstateListing` traz `offers.itemListElement` com 15 anúncios
por página, cada um com preço, área (`floorSize`), quartos, banheiros,
bairro (`addressLocality`) e a imobiliária anunciante.

Por que não parsear o slug da URL (abordagem anterior): boa parte dos
anúncios de apartamento não tem o segmento `-NNNm2` na URL, então a área
saía nula e o anúncio era descartado — era a causa dos ~2 resultados por
busca. O JSON-LD tem a área de todos.

Os parâmetros de filtro da URL (preço, tipo) são ignorados pelo site, então
a filtragem é feita aqui e reforçada depois por services/validacao.py.
"""
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from scraper.parser import calcular_preco_m2, extrair_construtora, normalizar_cidade
from services.texto import sem_acento

logger = logging.getLogger(__name__)

CHAVESNAMAO_BASE = "https://www.chavesnamao.com.br"
# Só ~30% de cada página cai na faixa de preço pedida (o site não filtra
# preço), então compensa varrer mais páginas — são gratuitas e paralelas.
MAX_PAGINAS = int(os.getenv("CHAVESNAMAO_MAX_PAGINAS", "12"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Não existe mapa de cidades aqui, e não deve existir: o padrão da URL é
# sempre `{sigla-do-estado}-{cidade}`.
#
# Havia um dicionário mapeando ESTADO → CAPITAL, aplicado a qualquer busca
# daquele estado. Buscar "Caucaia, CE" montava a URL de Fortaleza e devolvia
# 70 anúncios — nenhum de Caucaia, sem erro nenhum. O mesmo com Campinas,
# que virava São Paulo. Medido em 29/07/2026: 0 de 70 anúncios da cidade
# pedida. É o pior tipo de falha: dado de outra praça apresentado como certo.


def _build_url(cidade: str, estado: str, preco_min: float, preco_max: float, quartos: int | None, pagina: int = 1) -> str:
    """
    Monta a URL de busca.

    O tipo de imóvel e o nº de quartos são filtrados pelo PATH — na query
    string o site os ignora e devolve casas, terrenos e prédios junto.
    Faixa de preço não tem filtro server-side em nenhum formato conhecido;
    é aplicada no parsing.
    """
    cidade_slug = sem_acento(cidade).lower().strip().replace(" ", "-")
    estado_cidade = f"{sem_acento(estado).lower().strip()}-{cidade_slug}"
    url = f"{CHAVESNAMAO_BASE}/apartamentos-a-venda/{estado_cidade}/"
    if quartos:
        url += f"{int(quartos)}-quartos/"
    if pagina > 1:
        # O parâmetro é `pg`. Com `pagina` o site devolve sempre a página 1
        # silenciosamente — era por isso que a paginação não surtia efeito.
        url += f"?pg={pagina}"
    return url


# Tipos de imóvel do schema.org que contam como apartamento para precificação.
_TIPOS_ACEITOS = {"Apartment", "Residence", "Accommodation"}


def _extrair_ofertas_jsonld(html: str) -> list[dict]:
    """Devolve os itens de `offers.itemListElement` do bloco RealEstateListing."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(dados, dict) or dados.get("@type") != "RealEstateListing":
            continue
        ofertas = dados.get("offers")
        if isinstance(ofertas, dict):
            return ofertas.get("itemListElement", []) or []
    return []


def _area_de_floorsize(item: dict) -> float | None:
    """floorSize vem como {'unitText': '63m²'} — extrai o número."""
    floor = item.get("floorSize") or {}
    texto = str(floor.get("unitText") or floor.get("value") or "")
    m = re.search(r"(\d+(?:[.,]\d+)?)", texto)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _int_ou_none(valor) -> int | None:
    try:
        return int(valor) if valor is not None and str(valor).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _parse_oferta(oferta: dict, cidade_normalizada: str) -> dict | None:
    """Converte um Offer do JSON-LD no dict padrão do pipeline."""
    item = oferta.get("itemOffered") or {}
    if item.get("@type") not in _TIPOS_ACEITOS:
        return None

    try:
        preco = float(oferta.get("price") or 0)
    except (TypeError, ValueError):
        return None
    area = _area_de_floorsize(item)
    if not preco or not area or area <= 0:
        return None

    endereco = item.get("address") or {}
    titulo = str(oferta.get("name") or "").strip()
    url = str(oferta.get("url") or "")
    anunciante = (oferta.get("offeredBy") or {}).get("name")

    return {
        "id": str(uuid.uuid4()),
        "nome_anuncio": titulo,
        # O nome real do empreendimento é extraído do título pelo parser
        # compartilhado; não repetir o título aqui evita nome genérico.
        "nome_empreendimento": None,
        "construtora": extrair_construtora(titulo, anunciante),
        "cidade": cidade_normalizada,
        "bairro": endereco.get("addressLocality"),
        "portal": "chavesnamao",
        "preco": preco,
        "area_m2": area,
        "preco_m2": calcular_preco_m2(preco, area),
        # O JSON-LD ora traz número, ora string ("3") — normalizar para int
        # evita comparação str×int lá na frente no pipeline.
        "quartos": _int_ou_none(item.get("numberOfBedrooms") or item.get("numberOfRooms")),
        "banheiros": _int_ou_none(item.get("numberOfBathroomsTotal")),
        "vagas": None,
        "descricao": titulo[:300],
        "url_anuncio": url,
        "data_coleta": datetime.now(),
    }


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
        ofertas = _extrair_ofertas_jsonld(html)

        resultados = []
        for oferta in ofertas:
            item = _parse_oferta(oferta, cidade_normalizada)
            if item is None:
                continue

            # O site ignora os filtros da URL — aplicamos aqui.
            if not (preco_min <= item["preco"] <= preco_max):
                continue
            if quartos and item.get("quartos") and int(item["quartos"]) != int(quartos):
                continue

            # Dedup por ID do anúncio, compartilhado entre as páginas
            m = re.search(r"/id-(\d+)/", item["url_anuncio"])
            id_anuncio = m.group(1) if m else item["url_anuncio"]
            if id_anuncio in vistos_global:
                continue
            vistos_global.add(id_anuncio)

            resultados.append(item)

        logger.info(f"ChavesNaMão p{pagina}: {len(ofertas)} ofertas → {len(resultados)} válidas")
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
    nome_cidade = sem_acento(partes[0].strip()).lower().replace(" ", "-")
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
