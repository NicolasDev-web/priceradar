"""Agente 3 — Netimóveis (scraping direto, sem proxy pago).

Estratégia: request direto com headers de browser + parse do JSON-LD
embutido no HTML. Netimóveis serve dados no HTML inicial sem JS obrigatório.
Fallback: parse de script tags com objeto window.__INITIAL_STATE__.
"""
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from scraper.browser import buscar_html_playwright, interceptar_api_playwright
from scraper.parser import (
    calcular_preco_m2,
    extrair_construtora,
    extrair_nome_empreendimento,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

NETIMOVEISS_BASE = "https://www.netimoveis.com"



def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_url(estado: str, cidade: str, preco_min: float, preco_max: float, quartos: int | None) -> str:
    # Netimoveis: /venda/apartamento/ESTADO/CIDADE
    url = f"{NETIMOVEISS_BASE}/venda/apartamento/{estado.lower()}/{cidade.lower()}"
    params = f"?preco_minimo={int(preco_min)}&preco_maximo={int(preco_max)}"
    if quartos:
        params += f"&dormitorios={quartos}"
    return url + params


def _parse_json_ld(html: str, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    resultados = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        if data.get("@type") != "ItemList":
            continue

        items = data.get("itemListElement", [])
        logger.info(f"Netimoveis JSON-LD: {len(items)} items")

        for entry in items:
            item = entry.get("item", entry)
            try:
                preco = item.get("offers", {}).get("price")
                area = item.get("floorSize", {}).get("value")
                if not preco or not area or float(area) == 0:
                    continue
                preco_f, area_f = float(preco), float(area)
                if not (preco_min <= preco_f <= preco_max):
                    continue

                quartos_val = item.get("numberOfBedrooms") or item.get("numberOfRooms")
                banheiros = item.get("numberOfBathroomsTotal")
                url_anuncio = item.get("url") or item.get("offers", {}).get("url", "")
                nome = item.get("name", "Sem título")
                descricao_full = item.get("description") or ""
                addr = item.get("address", {})
                bairro = addr.get("streetAddress") or addr.get("addressLocality")

                vagas_match = re.search(r"(\d+)\s*vaga", nome + " " + descricao_full, re.IGNORECASE)
                vagas = int(vagas_match.group(1)) if vagas_match else None

                resultados.append({
                    "id": str(uuid.uuid4()),
                    "nome_anuncio": nome,
                    "nome_empreendimento": extrair_nome_empreendimento(descricao_full) or nome,
                    "construtora": extrair_construtora(nome, descricao_full),
                    "cidade": cidade_normalizada,
                    "bairro": bairro,
                    "portal": "netimoveis",
                    "preco": preco_f,
                    "area_m2": area_f,
                    "preco_m2": calcular_preco_m2(preco_f, area_f),
                    "quartos": quartos_val,
                    "banheiros": banheiros,
                    "vagas": vagas,
                    "descricao": descricao_full[:300],
                    "url_anuncio": url_anuncio or NETIMOVEISS_BASE,
                    "data_coleta": datetime.now(),
                })
            except Exception as e:
                logger.warning(f"Netimoveis: erro ao processar item: {e}")

        break

    return resultados


def _extrair_de_json_api(data: Any, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    """Extrai listings de uma resposta JSON de API interceptada pelo Playwright."""
    resultados = []
    listings = []

    if isinstance(data, list):
        listings = data
    elif isinstance(data, dict):
        for key in ("imoveis", "listings", "results", "data", "items", "content"):
            val = data.get(key)
            if isinstance(val, list):
                listings = val
                break
        if not listings:
            listings = [data]

    for item in listings:
        if not isinstance(item, dict):
            continue
        try:
            preco = float(item.get("preco") or item.get("price") or item.get("valor") or 0)
            area = float(item.get("area") or item.get("areaUtil") or item.get("totalArea") or item.get("areaTotal") or 0)
            if preco == 0 or area == 0 or not (preco_min <= preco <= preco_max):
                continue
            titulo = item.get("titulo") or item.get("title") or item.get("nome") or "Sem título"
            url = item.get("url") or item.get("link") or item.get("permalink") or ""
            if url and not url.startswith("http"):
                url = NETIMOVEISS_BASE + url
            resultados.append({
                "id": str(uuid.uuid4()),
                "nome_anuncio": titulo,
                "nome_empreendimento": titulo,
                "construtora": extrair_construtora(titulo, None),
                "cidade": cidade_normalizada,
                "bairro": item.get("bairro") or item.get("neighborhood") or item.get("endereco", {}).get("bairro"),
                "portal": "netimoveis",
                "preco": preco,
                "area_m2": area,
                "preco_m2": calcular_preco_m2(preco, area),
                "quartos": item.get("quartos") or item.get("dormitorios") or item.get("bedrooms"),
                "banheiros": item.get("banheiros") or item.get("bathrooms"),
                "vagas": item.get("vagas") or item.get("garagens"),
                "descricao": str(item.get("descricao") or item.get("description") or "")[:300],
                "url_anuncio": url or NETIMOVEISS_BASE,
                "data_coleta": datetime.now(),
            })
        except Exception as e:
            logger.warning(f"Netimoveis API item erro: {e}")

    return resultados


def _parse_initial_state(html: str, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    """Fallback: extrai window.__INITIAL_STATE__ ou similar de scripts inline."""
    for pattern in [
        r"window\.__INITIAL_STATE__\s*=\s*({.*?})(?:;|\s*</script>)",
        r"window\.__STORE__\s*=\s*({.*?})(?:;|\s*</script>)",
        r'"listings"\s*:\s*(\[.*?\])',
    ]:
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        listings = []
        if isinstance(raw, list):
            listings = raw
        elif isinstance(raw, dict):
            for key in ("listings", "imoveis", "results", "data"):
                val = raw.get(key)
                if isinstance(val, list):
                    listings = val
                    break

        resultados = []
        for item in listings:
            try:
                preco = float(item.get("price") or item.get("preco") or 0)
                area = float(item.get("area") or item.get("areaUtil") or item.get("totalArea") or 0)
                if preco == 0 or area == 0:
                    continue
                if not (preco_min <= preco <= preco_max):
                    continue
                titulo = item.get("title") or item.get("titulo") or "Sem título"
                url = item.get("url") or item.get("link") or ""
                if url and not url.startswith("http"):
                    url = NETIMOVEISS_BASE + url
                resultados.append({
                    "id": str(uuid.uuid4()),
                    "nome_anuncio": titulo,
                    "nome_empreendimento": titulo,
                    "construtora": extrair_construtora(titulo, None),
                    "cidade": cidade_normalizada,
                    "bairro": item.get("bairro") or item.get("neighborhood"),
                    "portal": "netimoveis",
                    "preco": preco,
                    "area_m2": area,
                    "preco_m2": calcular_preco_m2(preco, area),
                    "quartos": item.get("quartos") or item.get("bedrooms"),
                    "banheiros": item.get("banheiros") or item.get("bathrooms"),
                    "vagas": item.get("vagas") or item.get("garages"),
                    "descricao": str(item.get("descricao") or "")[:300],
                    "url_anuncio": url or NETIMOVEISS_BASE,
                    "data_coleta": datetime.now(),
                })
            except Exception:
                continue

        if resultados:
            return resultados

    return []


async def scrape_netimoveis(
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

    target_url = _build_url(estado, nome_cidade, preco_min, preco_max, quartos)

    # Tenta interceptar a chamada AJAX de listings (mais rico que o HTML inicial)
    padroes_api = ["/api/", "/imoveis", "/search", "/listings", "/busca"]
    respostas_api = await interceptar_api_playwright(target_url, "Netimoveis", padroes_api)

    resultados = []
    for resp in respostas_api:
        resultados.extend(_extrair_de_json_api(resp, cidade_normalizada, preco_min, preco_max))

    if not resultados:
        # Fallback: parse do HTML renderizado (JSON-LD ou __INITIAL_STATE__)
        html = await buscar_html_playwright(target_url, "Netimoveis")
        if html:
            resultados = _parse_json_ld(html, cidade_normalizada, preco_min, preco_max)
            if not resultados:
                resultados = _parse_initial_state(html, cidade_normalizada, preco_min, preco_max)

    logger.info(f"Netimoveis: {len(resultados)} anúncios encontrados")
    return resultados
