"""OLX — coleta da listagem React Server Components.

O HTML público traz os anúncios dentro de chamadas `self.__next_f.push`, no
payload do Next.js. O parser mantém o formato HTML antigo como fallback para
uma eventual reversão do portal.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from scraper.http import buscar_html
from scraper.paginacao import paginar
from scraper.parser import (
    calcular_preco_m2,
    extrair_construtora,
    extrair_fotos,
    fotos_de_card,
    limpar_preco,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

OLX_BASE_URL = "https://www.olx.com.br"
MAX_PAGINAS_OLX = int(os.getenv("OLX_MAX_PAGINAS", "5"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ESTADOS_MAP = {
    "ac": "estado-ac", "al": "estado-al", "ap": "estado-ap", "am": "estado-am",
    "ba": "estado-ba", "ce": "estado-ce", "df": "estado-df", "es": "estado-es",
    "go": "estado-go", "ma": "estado-ma", "mt": "estado-mt", "ms": "estado-ms",
    "mg": "estado-mg", "pa": "estado-pa", "pb": "estado-pb", "pr": "estado-pr",
    "pe": "estado-pe", "pi": "estado-pi", "rj": "estado-rj", "rn": "estado-rn",
    "rs": "estado-rs", "ro": "estado-ro", "rr": "estado-rr", "sc": "estado-sc",
    "sp": "estado-sp", "se": "estado-se", "to": "estado-to",
}


def build_olx_url(cidade: str, estado: str, preco_min: float, preco_max: float) -> str:
    estado_path = ESTADOS_MAP.get(estado.lower(), f"estado-{estado.lower()}")
    cidade_q = cidade.replace('-', ' ').replace('  ', ' ').strip()
    return (
        f"{OLX_BASE_URL}/imoveis/venda/apartamentos/{estado_path}"
        f"?pe={int(preco_max)}&ps={int(preco_min)}&q={cidade_q}"
    )


def _extrair_float(m: re.Match | None) -> float | None:
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', '.'))
    except Exception:
        return None


def _extrair_int(m: re.Match | None) -> int | None:
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def parse_detalhes_olx(texto: str) -> dict:
    return {
        "area_m2":   _extrair_float(re.search(r"(\d+(?:,\d+)?)\s*m[²2]", texto)),
        "quartos":   _extrair_int(re.search(r"(\d+)\s*quarto", texto, re.IGNORECASE)),
        "banheiros": _extrair_int(re.search(r"(\d+)\s*banheiro", texto, re.IGNORECASE)),
        "vagas":     _extrair_int(re.search(r"(\d+)\s*vaga", texto, re.IGNORECASE)),
    }


def _extrair_ads_rsc(html: str) -> list[dict]:
    """Lê o maior array `ads` dos chunks RSC e remove repetidos por listId."""
    chunks: list[str] = []
    for bloco in re.findall(r"self\.__next_f\.push\((\[.*?\])\)</script>", html, re.DOTALL):
        try:
            valor = json.loads(bloco)
        except json.JSONDecodeError:
            continue
        if len(valor) > 1 and isinstance(valor[1], str):
            chunks.append(valor[1])

    texto = "".join(chunks)
    decoder = json.JSONDecoder()
    candidatos: list[list[dict]] = []
    for match in re.finditer(r'"ads":', texto):
        try:
            valor, _ = decoder.raw_decode(texto, match.end())
        except json.JSONDecodeError:
            continue
        if isinstance(valor, list) and all(isinstance(item, dict) for item in valor):
            candidatos.append(valor)

    if not candidatos:
        return []

    vistos: set[str] = set()
    anuncios: list[dict] = []
    for item in max(candidatos, key=len):
        chave = str(item.get("listId") or item.get("url") or "")
        if chave and chave not in vistos:
            vistos.add(chave)
            anuncios.append(item)
    return anuncios


def _propriedades(ad: dict) -> dict[str, str]:
    resultado: dict[str, str] = {}
    for prop in ad.get("properties") or []:
        if isinstance(prop, dict) and prop.get("name") and prop.get("value") is not None:
            resultado[str(prop["name"])] = str(prop["value"])
    return resultado


def _bairro_da_localizacao(localizacao: str) -> str | None:
    partes = [p.strip() for p in localizacao.split(",") if p.strip()]
    if len(partes) < 2:
        return None
    return re.split(r"\s+-\s+DDD\s*\d+", partes[1], maxsplit=1, flags=re.IGNORECASE)[0].strip() or None


def _preco_rsc(ad: dict) -> float | None:
    valor = ad.get("price")
    if isinstance(valor, (int, float)) and valor > 0:
        return float(valor)
    texto = str(ad.get("priceValue") or valor or "")
    if "," in texto:
        return limpar_preco(texto)
    digitos = re.sub(r"\D", "", texto)
    return float(digitos) if digitos else None


def _parse_ad_rsc(ad: dict, cidade_normalizada: str) -> dict | None:
    try:
        propriedades = _propriedades(ad)
        preco = _preco_rsc(ad)
        area = _extrair_float(re.search(r"(\d+(?:[,.]\d+)?)\s*m[²2]", propriedades.get("size", "")))
        if preco is None or area is None or area <= 0:
            return None

        nome = str(ad.get("subject") or "Sem título").strip()
        localizacao = str(ad.get("location") or "").strip()
        bairro = _bairro_da_localizacao(localizacao)
        descricao = " · ".join(x for x in (nome, localizacao) if x)
        return {
            "id": str(uuid.uuid4()),
            "nome_anuncio": nome,
            "nome_empreendimento": nome,
            "construtora": extrair_construtora(nome, descricao),
            "cidade": cidade_normalizada,
            "bairro": bairro,
            "portal": "olx",
            "preco": preco,
            "area_m2": area,
            "preco_m2": calcular_preco_m2(preco, area),
            "quartos": _extrair_int(re.search(r"(\d+)", propriedades.get("rooms", ""))),
            "banheiros": _extrair_int(re.search(r"(\d+)", propriedades.get("bathrooms", ""))),
            "vagas": _extrair_int(re.search(r"(\d+)", propriedades.get("garage_spaces", ""))),
            "descricao": descricao[:300],
            "url_anuncio": str(ad.get("url") or OLX_BASE_URL),
            "data_coleta": datetime.now(),
            "fotos": extrair_fotos(ad.get("images") or [], OLX_BASE_URL),
        }
    except Exception as e:
        logger.warning(f"OLX: erro ao parsear anúncio RSC: {e}")
        return None


def parse_olx_html(html: str, cidade_normalizada: str) -> list[dict]:
    ads_rsc = _extrair_ads_rsc(html)
    if ads_rsc:
        resultados = [item for ad in ads_rsc if (item := _parse_ad_rsc(ad, cidade_normalizada))]
        logger.info(f"OLX: {len(resultados)}/{len(ads_rsc)} anúncios válidos no payload RSC")
        return resultados

    soup = BeautifulSoup(html, 'lxml')
    cards = soup.select('li[data-lurker-detail="ad_list"]')
    if not cards:
        cards = soup.select('section[data-testid="ad-card"]')

    logger.info(f"OLX: {len(cards)} cards encontrados")
    resultados = []

    for card in cards:
        try:
            el_nome = (
                card.select_one('h2[class*="title"]')
                or card.select_one('a[data-lurker-detail="ad_title"]')
            )
            nome_anuncio = el_nome.get_text(strip=True) if el_nome else 'Sem título'

            el_preco = card.select_one('h3[class*="price"]') or card.select_one('span[class*="price"]')
            preco = limpar_preco(el_preco.get_text(strip=True) if el_preco else '')

            # Detalhes em texto livre
            el_tags = card.select_one('ul[class*="tags"]')
            texto_detalhes = el_tags.get_text(separator=' ', strip=True) if el_tags else ''
            detalhes = parse_detalhes_olx(texto_detalhes)
            area = detalhes.get("area_m2")

            el_end = card.select_one('p[class*="location"]')
            endereco = el_end.get_text(strip=True) if el_end else ''
            bairro = endereco.split(',')[0].strip() if endereco else None

            el_link = card.select_one('a[data-lurker-detail="ad_title"]') or card.select_one('a[href*="olx.com.br"]')
            href = el_link.get('href', '') if el_link else ''

            if preco is None or area is None or area == 0:
                continue

            preco_m2 = calcular_preco_m2(preco, area)
            descricao = card.get_text(separator=' ', strip=True)[:300]
            construtora = extrair_construtora(nome_anuncio, descricao)

            resultados.append({
                'id': str(uuid.uuid4()),
                'nome_anuncio': nome_anuncio,
                'nome_empreendimento': nome_anuncio,
                'construtora': construtora,
                'cidade': cidade_normalizada,
                'bairro': bairro,
                'portal': 'olx',
                'preco': preco,
                'area_m2': area,
                'preco_m2': preco_m2,
                'quartos': detalhes.get("quartos"),
                'banheiros': detalhes.get("banheiros"),
                'vagas': detalhes.get("vagas"),
                'descricao': descricao,
                'url_anuncio': href or OLX_BASE_URL,
                'data_coleta': datetime.now(),
                'fotos': fotos_de_card(card, OLX_BASE_URL),
            })
        except Exception as e:
            logger.warning(f"OLX: erro ao parsear card: {e}")
            continue

    return resultados


async def scrape_olximoveis(
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
) -> list[dict]:
    cidade_normalizada = normalizar_cidade(cidade.split(',')[0])
    base_url = build_olx_url(cidade, estado, preco_min, preco_max)

    async def buscar_pagina(pagina: int) -> list[dict]:
        url = base_url if pagina == 1 else f"{base_url}&o={pagina}"
        logger.info(f"Scraping OLX p{pagina}: {url}")
        try:
            html = await buscar_html(url, "OLX")
            if not html or len(html) < 1000:
                logger.warning(f"OLX p{pagina}: resposta vazia ou muito curta")
                return []
            return parse_olx_html(html, cidade_normalizada)
        except Exception as e:
            logger.error(f"OLX p{pagina}: erro no scraping: {e}")
            return []

    return await paginar(buscar_pagina, MAX_PAGINAS_OLX, "OLX")
