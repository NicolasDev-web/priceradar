"""Agente 1 — Mercado Livre Imóveis.

Usa Playwright (browser real, headless, gratuito) para renderizar a página de
listagens do Mercado Livre Imóveis e extrair os dados dos anúncios.
A API REST do ML exige OAuth desde 2024; o site público ainda é acessível.
"""
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from scraper.browser import buscar_html_playwright, interceptar_api_playwright
from scraper.parser import calcular_preco_m2, extrair_construtora, normalizar_cidade
from services.texto import sem_acento

logger = logging.getLogger(__name__)

ML_SITE = "https://imoveis.mercadolivre.com.br"

_SIGLA_ESTADO = {
    "ac": "acre", "al": "alagoas", "ap": "amapa", "am": "amazonas",
    "ba": "bahia", "ce": "ceara", "df": "distrito-federal", "es": "espirito-santo",
    "go": "goias", "ma": "maranhao", "mt": "mato-grosso", "ms": "mato-grosso-do-sul",
    "mg": "minas-gerais", "pa": "para", "pb": "paraiba", "pr": "parana",
    "pe": "pernambuco", "pi": "piaui", "rj": "rio-de-janeiro",
    "rn": "rio-grande-do-norte", "rs": "rio-grande-do-sul", "ro": "rondonia",
    "rr": "roraima", "sc": "santa-catarina", "sp": "sao-paulo",
    "se": "sergipe", "to": "tocantins",
}


def _build_url(cidade_slug: str, estado_slug: str, preco_min: float, preco_max: float, quartos: int | None) -> str:
    url = f"{ML_SITE}/apartamentos_venda/{estado_slug}-{cidade_slug}/"
    params = f"?preco_de={int(preco_min)}&preco_ate={int(preco_max)}"
    if quartos:
        params += f"&BEDROOMS_TYPES={quartos}-bedroom"
    return url + params


def _limpar_preco(texto: str) -> float | None:
    texto = re.sub(r"[R$\s\.]", "", texto).replace(",", ".")
    m = re.search(r"\d[\d.]*", texto)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def _limpar_area(texto: str) -> float | None:
    texto = re.sub(r"[m²\s]", "", texto).replace(",", ".")
    m = re.search(r"\d[\d.]*", texto)
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None


def _parse_html(html: str, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    """Extrai listings do HTML renderizado pelo Playwright."""
    soup = BeautifulSoup(html, "lxml")
    resultados = []

    # Tenta JSON-LD primeiro (mais confiável)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if data.get("@type") != "ItemList":
            continue
        for entry in data.get("itemListElement", []):
            item = entry.get("item", entry)
            try:
                preco = float(item.get("offers", {}).get("price") or 0)
                area = float(item.get("floorSize", {}).get("value") or 0)
                if preco == 0 or area == 0 or not (preco_min <= preco <= preco_max):
                    continue
                nome = item.get("name", "Sem título")
                addr = item.get("address", {})
                bairro = addr.get("streetAddress") or addr.get("addressLocality")
                quartos_val = item.get("numberOfBedrooms") or item.get("numberOfRooms")
                url_anuncio = item.get("url") or ML_SITE
                resultados.append({
                    "id": str(uuid.uuid4()),
                    "nome_anuncio": nome,
                    "nome_empreendimento": nome,
                    "construtora": extrair_construtora(nome, None),
                    "cidade": cidade_normalizada,
                    "bairro": bairro,
                    "portal": "mercadolivre",
                    "preco": preco,
                    "area_m2": area,
                    "preco_m2": calcular_preco_m2(preco, area),
                    "quartos": quartos_val,
                    "banheiros": None,
                    "vagas": None,
                    "descricao": item.get("description", "")[:300],
                    "url_anuncio": url_anuncio,
                    "data_coleta": datetime.now(),
                })
            except Exception as e:
                logger.warning(f"MercadoLivre: erro no item JSON-LD: {e}")
        if resultados:
            return resultados

    # Fallback: parse HTML dos cards de anúncio
    cards = soup.select("li.results-item, div.andes-card, article.poly-card")
    logger.info(f"MercadoLivre HTML cards: {len(cards)}")
    for card in cards:
        try:
            titulo_el = card.select_one("h2, .poly-component__title, .item-title")
            preco_el = card.select_one(".andes-money-amount__fraction, .price-tag-fraction, .poly-price__current")
            area_el = card.select_one("[class*='surface'], [class*='area']")
            link_el = card.select_one("a[href]")

            if not titulo_el or not preco_el:
                continue

            preco = _limpar_preco(preco_el.get_text())
            if not preco or not (preco_min <= preco <= preco_max):
                continue

            area_txt = area_el.get_text() if area_el else ""
            area = _limpar_area(area_txt) if area_txt else None
            if not area or area <= 0:
                continue

            nome = titulo_el.get_text(strip=True)
            url_anuncio = link_el["href"] if link_el else ML_SITE

            resultados.append({
                "id": str(uuid.uuid4()),
                "nome_anuncio": nome,
                "nome_empreendimento": nome,
                "construtora": extrair_construtora(nome, None),
                "cidade": cidade_normalizada,
                "bairro": None,
                "portal": "mercadolivre",
                "preco": preco,
                "area_m2": area,
                "preco_m2": calcular_preco_m2(preco, area),
                "quartos": None,
                "banheiros": None,
                "vagas": None,
                "descricao": nome[:300],
                "url_anuncio": url_anuncio,
                "data_coleta": datetime.now(),
            })
        except Exception as e:
            logger.warning(f"MercadoLivre: erro no card HTML: {e}")

    return resultados


def _extrair_de_api_ml(data: Any, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    """Extrai listings de uma resposta JSON interceptada da API do ML."""
    resultados = []
    items = []
    if isinstance(data, dict):
        items = data.get("results", data.get("elements", data.get("items", [])))
    elif isinstance(data, list):
        items = data
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            preco = float(item.get("price") or item.get("sale_price", {}).get("amount") or 0)
            if not preco or not (preco_min <= preco <= preco_max):
                continue
            atribs = {a.get("id"): a.get("value_name") for a in item.get("attributes", [])}
            area_str = atribs.get("TOTAL_AREA") or atribs.get("COVERED_AREA")
            if not area_str:
                continue
            area = float(str(area_str).replace(",", ".").split()[0])
            if area <= 0:
                continue
            quartos_str = atribs.get("BEDROOMS")
            titulo = item.get("title", "Sem título")
            url = item.get("permalink", ML_SITE)
            loc = item.get("location", {})
            bairro = loc.get("neighborhood", {}).get("name") or loc.get("city", {}).get("name")
            resultados.append({
                "id": str(uuid.uuid4()),
                "nome_anuncio": titulo,
                "nome_empreendimento": titulo,
                "construtora": extrair_construtora(titulo, None),
                "cidade": cidade_normalizada,
                "bairro": bairro,
                "portal": "mercadolivre",
                "preco": preco,
                "area_m2": area,
                "preco_m2": calcular_preco_m2(preco, area),
                "quartos": int(quartos_str) if quartos_str and str(quartos_str).isdigit() else None,
                "banheiros": None,
                "vagas": None,
                "descricao": titulo[:300],
                "url_anuncio": url,
                "data_coleta": datetime.now(),
            })
        except Exception as e:
            logger.warning(f"MercadoLivre API item erro: {e}")
    return resultados


async def scrape_mercadolivre(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    partes = cidade.strip().split(",")
    nome_cidade = sem_acento(partes[0].strip()).lower().replace(" ", "-")
    sigla = partes[1].strip().lower() if len(partes) > 1 else "sp"
    estado_slug = _SIGLA_ESTADO.get(sigla, sigla)
    cidade_normalizada = normalizar_cidade(partes[0].strip())

    target_url = _build_url(nome_cidade, estado_slug, preco_min, preco_max, quartos)

    # Intercepta chamadas da API interna do ML feitas pelo browser
    padroes_api = ["api.mercadolibre.com", "/search", "/items"]
    respostas_api = await interceptar_api_playwright(target_url, "MercadoLivre", padroes_api,
                                                      wait_selector="li.results-item, .poly-card, .ui-search-result")
    resultados = []
    for resp in respostas_api:
        resultados.extend(_extrair_de_api_ml(resp, cidade_normalizada, preco_min, preco_max))

    if not resultados:
        # Fallback: parse do HTML renderizado
        html = await buscar_html_playwright(target_url, "MercadoLivre")
        if html:
            resultados = _parse_html(html, cidade_normalizada, preco_min, preco_max)

    logger.info(f"MercadoLivre: {len(resultados)} anúncios encontrados")
    return resultados
