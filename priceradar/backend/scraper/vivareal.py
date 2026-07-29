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
    classificar_edificacao,
    extrair_amenidades,
    extrair_bairro_do_slug,
    extrair_construtora,
    extrair_nome_empreendimento,
    normalizar_cidade,
)

logger = logging.getLogger(__name__)

VIVAREAL_BASE_URL = os.getenv("VIVAREAL_BASE_URL", "https://www.vivareal.com.br")
# 2 paginas: a 3a raramente traz item novo apos dedup e custa 1 credito.
MAX_PAGINAS = int(os.getenv("VIVAREAL_MAX_PAGINAS", "2"))

# O VivaReal usa o nome do estado por extenso no path — com uma exceção:
# São Paulo usa a sigla. `/venda/sao-paulo/campinas/` devolve 404, enquanto
# `/venda/sp/campinas/` funciona (provável colisão entre o estado e a capital
# homônima). Medido em 29/07/2026 em 9 cidades de 7 estados; SP é o único caso.
_ESTADO_SLUG = {
    "ac": "acre", "al": "alagoas", "ap": "amapa", "am": "amazonas",
    "ba": "bahia", "ce": "ceara", "df": "distrito-federal", "es": "espirito-santo",
    "go": "goias", "ma": "maranhao", "mt": "mato-grosso",
    "ms": "mato-grosso-do-sul", "mg": "minas-gerais", "pa": "para",
    "pb": "paraiba", "pr": "parana", "pe": "pernambuco", "pi": "piaui",
    "rj": "rio-de-janeiro", "rn": "rio-grande-do-norte",
    "rs": "rio-grande-do-sul", "ro": "rondonia", "rr": "roraima",
    "sc": "santa-catarina", "sp": "sp", "se": "sergipe", "to": "tocantins",
}

# Forma alternativa do estado, tentada quando a primeira devolve 404. Evita
# que uma exceção não mapeada zere a fonte inteira numa cidade nova.
_ESTADO_ALTERNATIVO = {"sp": "sao-paulo"}


def _extrair_estado_cidade(cidade_str: str) -> tuple[str, str]:
    """
    Devolve (estado_slug, cidade_slug) prontos para a URL.

    O acento precisa sair: `/venda/goias/goiânia/` devolve 404 e
    `/venda/goias/goiania/` devolve 200.
    """
    partes = cidade_str.strip().split(',')
    cidade = normalizar_cidade(partes[0]).replace(' ', '-')
    sigla = normalizar_cidade(partes[1]) if len(partes) > 1 else 'sp'
    estado = _ESTADO_SLUG.get(sigla, sigla)
    return estado, cidade


def build_vivareal_url(
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
    pagina: int = 1,
) -> str:
    # Bairro entra no PATH, não na query string: `&bairros=` é ignorado pelo
    # site, enquanto `/bairros/{slug}/` filtra de verdade — medido em 29/07/2026,
    # 25 de 30 anúncios do bairro pedido contra 3 de 30 sem o filtro.
    caminho_bairro = ""
    if bairro:
        slug = normalizar_cidade(bairro).replace(' ', '-')
        if slug:
            caminho_bairro = f"bairros/{slug}/"

    url = (
        f"{VIVAREAL_BASE_URL}/venda/{estado}/{cidade}/{caminho_bairro}"
        f"apartamento_residencial/?preco_de={int(preco_min)}&preco_ate={int(preco_max)}"
    )
    if quartos:
        url += f"&quartos={quartos}"
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
        logger.info(f"VivaReal JSON-LD: {len(items)} items")

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
                # O JSON-LD não traz bairro: `addressLocality` é a cidade e
                # `streetAddress` é o logradouro. O bairro só existe no slug.
                addr = item.get('address', {})
                endereco = addr.get('streetAddress')
                bairro_item = extrair_bairro_do_slug(url_anuncio, cidade_normalizada)

                # Torre x bloco: amenityFeature traz 'Elevator' de forma estruturada.
                amenidades = extrair_amenidades(item)
                tipo_edificacao = classificar_edificacao(amenidades, f'{nome} {descricao_full}')

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
                    'tipo_edificacao': tipo_edificacao,
                    'portal': 'vivareal',
                    'preco': float(preco),
                    'area_m2': float(area),
                    'preco_m2': calcular_preco_m2(float(preco), float(area)),
                    'quartos': quartos_val,
                    'banheiros': banheiros,
                    'vagas': vagas,
                    'descricao': descricao,
                    'url_anuncio': url_anuncio or VIVAREAL_BASE_URL,
                    'data_coleta': datetime.now(),
                })
            except Exception as e:
                logger.warning(f"VivaReal: erro ao processar item: {e}")

        break  # só precisa do primeiro ItemList

    return resultados


async def _fetch_pagina_vivareal(
    cidade_slug: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None,
    pagina: int,
    cidade_normalizada: str,
) -> list[dict]:
    url = build_vivareal_url(cidade_slug, estado, preco_min, preco_max, quartos, bairro, pagina)
    html = await buscar_html(url, f"VivaReal p{pagina}")

    # O path do estado tem exceções (SP usa sigla, o resto usa o nome por
    # extenso). Se a primeira forma não trouxe nada, tenta a alternativa antes
    # de desistir — assim uma cidade nova não zera a fonte por causa do mapa.
    if html is None:
        alternativo = _ESTADO_ALTERNATIVO.get(estado) or next(
            (sigla for sigla, nome in _ESTADO_SLUG.items() if nome == estado and sigla != estado),
            None,
        )
        if alternativo:
            logger.info(f"VivaReal p{pagina}: tentando estado alternativo '{alternativo}'")
            url_alt = build_vivareal_url(cidade_slug, alternativo, preco_min, preco_max, quartos, bairro, pagina)
            html = await buscar_html(url_alt, f"VivaReal p{pagina} (alt)")

    if html is None:
        logger.info(f"VivaReal p{pagina}: acesso falhou — tentando Playwright")
        html = await buscar_html_playwright(url, f"VivaReal p{pagina}")
    if html is None:
        return []
    return _parse_json_ld(html, cidade_normalizada, preco_min, preco_max)


async def scrape_vivareal(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    estado, cidade_slug = _extrair_estado_cidade(cidade)
    cidade_normalizada = normalizar_cidade(cidade.split(',')[0])

    tarefas = [
        _fetch_pagina_vivareal(cidade_slug, estado, preco_min, preco_max, quartos, bairro, p, cidade_normalizada)
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

    logger.info(f"VivaReal: {len(resultados)} anúncios únicos ({MAX_PAGINAS} páginas)")
    return resultados
