"""OLX — acesso destravado, parser desatualizado.

Estado em 29/07/2026: com a camada de acesso escalonada (curl-cffi), o OLX
voltou a responder HTTP 200 — não está mais bloqueado. Porém os seletores
CSS abaixo (`li[data-lurker-detail=ad_list]`, `section[data-testid=ad-card]`)
não existem mais no HTML atual: a listagem passou a ser servida via React
Server Components (`self.__next_f`), sem JSON-LD de ItemList.

Para reativar é preciso reescrever `parse_olx_html` lendo o payload RSC.
Prioridade baixa: o OLX concentra revenda por pessoa física, enquanto o
PriceRadar compara lançamentos de construtora.
"""
import logging
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from scraper.http import buscar_html
from scraper.parser import (
    calcular_preco_m2,
    extrair_construtora,
    limpar_preco,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

OLX_BASE_URL = "https://www.olx.com.br"

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


def parse_olx_html(html: str, cidade_normalizada: str) -> list[dict]:
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
    url = build_olx_url(cidade, estado, preco_min, preco_max)
    logger.info(f"Scraping OLX: {url}")

    try:
        # O OLX bloqueia httpx pela assinatura TLS. Com a camada de acesso
        # escalonada (curl-cffi imitando Chrome) ele voltou a responder 200.
        html = await buscar_html(url, "OLX")

        if not html or len(html) < 1000:
            logger.warning("OLX: resposta vazia ou muito curta — possível bloqueio")
            return []

        return parse_olx_html(html, cidade_normalizada)

    except Exception as e:
        logger.error(f"Erro no scraping OLX: {e}")
        return []
