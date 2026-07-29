"""123Imóveis — scraping direto via httpx (SSR com JSON-LD).

A plataforma 123i.com.br renderiza os listings no HTML inicial via JSON-LD,
sem precisar de JavaScript ou proxy pago.
"""
import asyncio
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime

import httpx

from scraper.parser import calcular_preco_m2, extrair_construtora, extrair_nome_empreendimento, normalizar_cidade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.123i.com.br"
MAX_PAGINAS = int(os.getenv("CIENTO23_MAX_PAGINAS", "5"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com/",
}

_ESTADOS = {
    "ac": "acre", "al": "alagoas", "ap": "amapa", "am": "amazonas",
    "ba": "bahia", "ce": "ceara", "df": "distrito-federal", "es": "espirito-santo",
    "go": "goias", "ma": "maranhao", "mt": "mato-grosso", "ms": "mato-grosso-do-sul",
    "mg": "minas-gerais", "pa": "para", "pb": "paraiba", "pr": "parana",
    "pe": "pernambuco", "pi": "piaui", "rj": "rio-de-janeiro",
    "rn": "rio-grande-do-norte", "rs": "rio-grande-do-sul", "ro": "rondonia",
    "rr": "roraima", "sc": "santa-catarina", "sp": "sao-paulo",
    "se": "sergipe", "to": "tocantins",
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_url(estado: str, cidade: str, preco_min: float, preco_max: float, quartos: int | None, pagina: int = 1) -> str:
    estado_slug = _ESTADOS.get(estado.lower(), estado.lower())
    cidade_slug = _sem_acento(cidade).lower().replace(" ", "-")
    url = f"{BASE_URL}/venda/{estado_slug}/{cidade_slug}/?tipo=APARTAMENTO&precoMin={int(preco_min)}&precoMax={int(preco_max)}"
    if quartos:
        url += f"&dormitorios={quartos}"
    if pagina > 1:
        url += f"&pagina={pagina}"
    return url


def _parse_json_ld(html: str, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    from bs4 import BeautifulSoup
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
        logger.info(f"123i JSON-LD: {len(items)} items")

        for entry in items:
            item = entry.get("item", entry)
            try:
                preco = item.get("offers", {}).get("price")
                area_val = item.get("floorSize", {})
                area = area_val.get("value") if isinstance(area_val, dict) else None
                if not preco or not area or float(area) == 0:
                    continue
                preco_f, area_f = float(preco), float(area)
                if not (preco_min <= preco_f <= preco_max):
                    continue

                quartos_val = item.get("numberOfBedrooms") or item.get("numberOfRooms")
                banheiros = item.get("numberOfBathroomsTotal")
                url_anuncio = item.get("url") or ""
                nome = item.get("name", "Sem título")
                descricao_full = item.get("description") or ""
                addr = item.get("address", {})
                bairro = addr.get("streetAddress") or addr.get("addressLocality")

                vagas_m = re.search(r"(\d+)\s*vaga", nome + " " + descricao_full, re.IGNORECASE)
                vagas = int(vagas_m.group(1)) if vagas_m else None

                resultados.append({
                    "id": str(uuid.uuid4()),
                    "nome_anuncio": nome,
                    "nome_empreendimento": extrair_nome_empreendimento(descricao_full) or nome,
                    "construtora": extrair_construtora(nome, descricao_full),
                    "cidade": cidade_normalizada,
                    "bairro": bairro,
                    "portal": "123imoveis",
                    "preco": preco_f,
                    "area_m2": area_f,
                    "preco_m2": calcular_preco_m2(preco_f, area_f),
                    "quartos": quartos_val,
                    "banheiros": banheiros,
                    "vagas": vagas,
                    "descricao": descricao_full[:300],
                    "url_anuncio": url_anuncio or BASE_URL,
                    "data_coleta": datetime.now(),
                })
            except Exception as e:
                logger.warning(f"123i: erro ao processar item: {e}")

        break  # só o primeiro ItemList

    # Fallback: tenta cards HTML quando não há JSON-LD
    if not resultados:
        resultados = _parse_cards_html(soup, cidade_normalizada, preco_min, preco_max)

    return resultados


def _parse_cards_html(soup, cidade_normalizada: str, preco_min: float, preco_max: float) -> list[dict]:
    cards = soup.select("[class*='listing-item'], [class*='property-card'], [data-cy*='result']")
    logger.info(f"123i HTML fallback: {len(cards)} cards")
    resultados = []
    for card in cards:
        try:
            preco_el = card.select_one("[class*='price'], [class*='valor']")
            if not preco_el:
                continue
            preco_txt = preco_el.get_text(strip=True)
            preco_txt = re.sub(r"[R$\s\.]", "", preco_txt).replace(",", ".")
            m = re.search(r"\d+", preco_txt)
            if not m:
                continue
            preco_f = float(m.group())
            if not (preco_min <= preco_f <= preco_max):
                continue

            area_el = card.select_one("[class*='area'], [class*='m2']")
            area_txt = area_el.get_text(strip=True) if area_el else ""
            m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*m", area_txt.replace(",", "."))
            if not m2:
                continue
            area_f = float(m2.group(1))
            if area_f <= 0:
                continue

            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else BASE_URL
            if url and not url.startswith("http"):
                url = BASE_URL + url

            titulo_el = card.select_one("h2, h3, [class*='title']")
            titulo = titulo_el.get_text(strip=True) if titulo_el else f"Apt {area_f}m²"

            resultados.append({
                "id": str(uuid.uuid4()),
                "nome_anuncio": titulo,
                "nome_empreendimento": titulo,
                "construtora": extrair_construtora(titulo, None),
                "cidade": cidade_normalizada,
                "bairro": None,
                "portal": "123imoveis",
                "preco": preco_f,
                "area_m2": area_f,
                "preco_m2": calcular_preco_m2(preco_f, area_f),
                "quartos": None,
                "banheiros": None,
                "vagas": None,
                "descricao": titulo[:300],
                "url_anuncio": url,
                "data_coleta": datetime.now(),
            })
        except Exception as e:
            logger.warning(f"123i card erro: {e}")

    return resultados


async def _fetch_pagina(
    client: httpx.AsyncClient,
    estado: str,
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    pagina: int,
    cidade_normalizada: str,
) -> list[dict]:
    url = _build_url(estado, cidade, preco_min, preco_max, quartos, pagina)
    try:
        resp = await client.get(url)
        logger.info(f"123i p{pagina}: status={resp.status_code} | {len(resp.content)//1024}KB")
        if resp.status_code != 200:
            return []
        html = resp.content.decode("utf-8", errors="replace")
        return _parse_json_ld(html, cidade_normalizada, preco_min, preco_max)
    except Exception as e:
        logger.error(f"123i p{pagina}: {e}")
        return []


async def scrape_123imoveis(
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

    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
        tarefas = [
            _fetch_pagina(client, estado, nome_cidade, preco_min, preco_max, quartos, p, cidade_normalizada)
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
            url = item.get("url_anuncio", "")
            if url and url not in vistos:
                vistos.add(url)
                resultados.append(item)
            elif not url:
                resultados.append(item)

    logger.info(f"123i: {len(resultados)} anúncios únicos encontrados ({MAX_PAGINAS} páginas)")
    return resultados
