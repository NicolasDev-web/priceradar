import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from scraper.browser import buscar_html_playwright
from scraper.http import buscar_html
from scraper.parser import (
    calcular_preco_m2,
    extrair_bairro_do_slug,
    extrair_construtora,
    extrair_nome_empreendimento,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

ZAP_BASE_URL = "https://www.zapimoveis.com.br"
# 2 paginas: a 3a raramente traz item novo apos dedup e custa 1 credito.
MAX_PAGINAS = int(os.getenv("ZAP_MAX_PAGINAS", "2"))


def build_zapimoveis_url(
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
    pagina: int = 1,
) -> str:
    url = f"{ZAP_BASE_URL}/venda/apartamentos/{estado}+{cidade}/?precoMinimo={int(preco_min)}&precoMaximo={int(preco_max)}"
    if quartos:
        url += f"&quartos={quartos}"
    # O Zap ignora bairro tanto na query quanto no path (testado em
    # 29/07/2026: ambos devolvem 404 ou o resultado sem filtro). O bairro
    # é aplicado depois, em services/search.py, sobre o campo já corrigido.
    if pagina > 1:
        url += f"&pagina={pagina}"
    return url


def _parse_json_ld(
    html: str,
    cidade_normalizada: str,
    preco_min: float = 0,
    preco_max: float = float('inf'),
) -> list[dict]:
    """Extrai listings do JSON-LD ItemList embutido no HTML."""
    soup = BeautifulSoup(html, 'lxml')
    resultados = []

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
        except (json.JSONDecodeError, TypeError):
            continue

        if data.get('@type') != 'ItemList':
            continue

        items = data.get('itemListElement', [])
        logger.info(f"Zap JSON-LD: {len(items)} items")

        for entry in items:
            item = entry.get('item', entry)
            try:
                preco = item.get('offers', {}).get('price')
                area = item.get('floorSize', {}).get('value')
                if not preco or not area or area == 0:
                    continue
                if not (preco_min <= float(preco) <= preco_max):
                    continue

                quartos_val = item.get('numberOfBedrooms') or item.get('numberOfRooms')
                banheiros = item.get('numberOfBathroomsTotal')
                url_anuncio = item.get('url', '') or item.get('offers', {}).get('url', '')
                nome = item.get('name', 'Sem título')
                descricao_full = item.get('description') or ''
                descricao = descricao_full[:300]
                # Mesma limitação do VivaReal: `addressLocality` é a cidade e
                # `streetAddress` é o logradouro. O bairro só existe no slug.
                addr = item.get('address', {})
                endereco = addr.get('streetAddress')
                bairro_item = extrair_bairro_do_slug(url_anuncio, cidade_normalizada)

                nome_emp = extrair_nome_empreendimento(descricao_full)
                construtora = extrair_construtora(nome, descricao_full)

                vagas_match = re.search(r'(\d+)\s*vaga', nome + ' ' + descricao, re.IGNORECASE)
                vagas = int(vagas_match.group(1)) if vagas_match else None

                resultados.append({
                    'id': str(uuid.uuid4()),
                    'nome_anuncio': nome,
                    'nome_empreendimento': nome_emp,
                    'construtora': construtora,
                    'cidade': cidade_normalizada,
                    'bairro': bairro_item,
                    'endereco': endereco,
                    'portal': 'zapimoveis',
                    'preco': float(preco),
                    'area_m2': float(area),
                    'preco_m2': calcular_preco_m2(float(preco), float(area)),
                    'quartos': quartos_val,
                    'banheiros': banheiros,
                    'vagas': vagas,
                    'descricao': descricao,
                    'url_anuncio': url_anuncio or ZAP_BASE_URL,
                    'data_coleta': datetime.now(),
                })
            except Exception as e:
                logger.warning(f"Zap: erro ao processar item: {e}")

        break  # só precisa do primeiro ItemList

    return resultados


async def _fetch_pagina_zap(
    cidade_nome: str,
    estado_lower: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None,
    pagina: int,
    cidade_normalizada: str,
) -> list[dict]:
    url = build_zapimoveis_url(cidade_nome, estado_lower, preco_min, preco_max, quartos, bairro, pagina)
    html = await buscar_html(url, f"Zap p{pagina}")
    if html is None:
        logger.info(f"Zap p{pagina}: ScraperAPI falhou — tentando Playwright")
        html = await buscar_html_playwright(url, f"Zap p{pagina}")
    if html is None:
        return []
    return _parse_json_ld(html, cidade_normalizada, preco_min, preco_max)


async def scrape_zapimoveis(
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    cidade_nome = cidade.split(',')[0].strip().lower().replace(' ', '-')
    estado_lower = estado.lower()
    cidade_normalizada = normalizar_cidade(cidade.split(',')[0])

    tarefas = [
        _fetch_pagina_zap(cidade_nome, estado_lower, preco_min, preco_max, quartos, bairro, p, cidade_normalizada)
        for p in range(1, MAX_PAGINAS + 1)
    ]
    paginas = await asyncio.gather(*tarefas, return_exceptions=True)

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

    logger.info(f"Zap: {len(resultados)} anúncios únicos ({MAX_PAGINAS} páginas)")
    return resultados
