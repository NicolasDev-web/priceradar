"""OLX — coleta da listagem React Server Components.

O HTML público traz os anúncios dentro de chamadas `self.__next_f.push`, no
payload do Next.js. O parser mantém o formato HTML antigo como fallback para
uma eventual reversão do portal.

Assertividade: a busca vai pelo município no path quando a região da OLX é
conhecida, e todo anúncio que declara outro município é descartado — a OLX
mistura a região metropolitana (Caucaia, Eusébio…) na busca por texto.
"""
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime
from urllib.parse import quote_plus

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
# Com o município no path quase toda página é aproveitável; `paginar` para
# sozinho quando um lote não traz anúncio novo, então busca pequena não paga o teto.
MAX_PAGINAS_OLX = int(os.getenv("OLX_MAX_PAGINAS", "10"))

# Resumo da última coleta, para scripts/validar_olx_pipeline.py.
ULTIMA_COLETA: dict = {}

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


# A OLX agrupa cidades por região de DDD, e o nome da região não sai do nome
# da cidade (Fortaleza → fortaleza-e-regiao, Recife → grande-recife). Com a
# região, a URL filtra o MUNICÍPIO no path; sem ela, a única opção é a busca
# por texto no estado (`q=`), que traz Caucaia, Eusébio etc. misturados.
# Semente com o que foi conferido nas páginas públicas; o resto é aprendido
# da URL dos próprios anúncios (ver `_aprender_regiao`).
_REGIOES_SEMENTE: dict[tuple[str, str], str] = {
    ("ce", "fortaleza"): "fortaleza-e-regiao",
    ("pe", "recife"): "grande-recife",
}
_regioes_aprendidas: dict[tuple[str, str], str] = {}

_URL_ANUNCIO = re.compile(r"^https?://([a-z]{2})\.olx\.com\.br/([a-z0-9-]+)/", re.IGNORECASE)
_SUFIXO_DDD = re.compile(r"\s+-\s+DDD\s*\d+\s*$", re.IGNORECASE)


def _chave_cidade(nome: str) -> str:
    """'São Paulo', 'sao-paulo' e 'SAO  PAULO' viram a mesma chave."""
    return re.sub(r"[\s\-]+", " ", normalizar_cidade(str(nome))).strip()


def _slug(nome: str) -> str:
    return _chave_cidade(nome).replace(" ", "-")


def regiao_olx(estado: str, cidade: str) -> str | None:
    chave = (estado.lower(), _slug(cidade))
    return _REGIOES_SEMENTE.get(chave) or _regioes_aprendidas.get(chave)


def _aprender_regiao(url_anuncio: str, cidade: str) -> None:
    """`https://ce.olx.com.br/fortaleza-e-regiao/imoveis/…` → região de Fortaleza.

    Só é chamada para anúncios cujo município já bateu com a cidade buscada.
    """
    m = _URL_ANUNCIO.match(url_anuncio or "")
    if not m or m.group(2).lower() == "imoveis":
        return
    chave = (m.group(1).lower(), _slug(cidade))
    if chave not in _REGIOES_SEMENTE and chave not in _regioes_aprendidas:
        _regioes_aprendidas[chave] = m.group(2).lower()
        logger.info(f"OLX: região aprendida para {chave[1]}/{chave[0]}: {_regioes_aprendidas[chave]}")


def _esquecer_regiao(estado: str, cidade: str) -> None:
    """Região aprendida que não abriu a página da cidade não é tentada de novo."""
    _regioes_aprendidas.pop((estado.lower(), _slug(cidade)), None)


def build_olx_url(
    cidade: str,
    estado: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None = None,
    bairro: str | None = None,
    pagina: int = 1,
    por_cidade: bool = True,
) -> str:
    """
    `por_cidade` e região conhecida → município (e bairro) no PATH:
    `/estado-ce/fortaleza-e-regiao/fortaleza[/coco]`. Senão, a busca antiga por
    texto no estado — o parser então exige que o anúncio declare o município.
    """
    estado_path = ESTADOS_MAP.get(estado.lower(), f"estado-{estado.lower()}")
    regiao = regiao_olx(estado, cidade) if por_cidade else None
    params = [f"ps={int(preco_min)}", f"pe={int(preco_max)}"]
    if regiao:
        caminho = f"{estado_path}/{regiao}/{_slug(cidade)}"
        if bairro and _slug(bairro):
            caminho += f"/{_slug(bairro)}"
    else:
        caminho = estado_path
        params.append(f"q={quote_plus(_chave_cidade(cidade))}")
    if quartos:
        # `ros` é o filtro de quartos da OLX; a validação ainda confere a
        # tipologia de cada anúncio, então um `ros` ignorado não faz estrago.
        params.append(f"ros={int(quartos)}")
    if pagina > 1:
        params.append(f"o={pagina}")
    return f"{OLX_BASE_URL}/imoveis/venda/apartamentos/{caminho}?{'&'.join(params)}"


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


def _texto(valor) -> str | None:
    return str(valor).strip() or None if valor is not None else None


def _municipio_e_bairro(ad: dict, cidade: str) -> tuple[str | None, str | None]:
    """
    Município e bairro do anúncio. Prefere o `locationDetails` estruturado;
    senão lê `location`, que vem como "Fortaleza, Cocó - DDD 85" ou só
    "Eusébio - DDD 85". Se a cidade buscada aparecer na segunda parte, a ordem
    veio invertida ("Cocó, Fortaleza") e é desfeita.
    """
    municipio = bairro = None
    detalhes = ad.get("locationDetails")
    if isinstance(detalhes, dict):
        municipio = _texto(detalhes.get("municipality") or detalhes.get("city"))
        bairro = _texto(detalhes.get("neighbourhood") or detalhes.get("neighborhood"))

    texto = _SUFIXO_DDD.sub("", str(ad.get("location") or "")).strip()
    partes = [p.strip() for p in texto.split(",") if p.strip()]
    if len(partes) >= 2:
        mun_txt, bairro_txt = partes[0], partes[1]
        alvo = _chave_cidade(cidade)
        if _chave_cidade(bairro_txt) == alvo and _chave_cidade(mun_txt) != alvo:
            mun_txt, bairro_txt = bairro_txt, mun_txt
        municipio = municipio or mun_txt
        bairro = bairro or bairro_txt
    elif partes:
        municipio = municipio or partes[0]
    return municipio, bairro


def _preco_rsc(ad: dict) -> float | None:
    valor = ad.get("price")
    if isinstance(valor, (int, float)) and valor > 0:
        return float(valor)
    texto = str(ad.get("priceValue") or valor or "")
    if "," in texto:
        return limpar_preco(texto)
    digitos = re.sub(r"\D", "", texto)
    return float(digitos) if digitos else None


def _parse_ad_rsc(ad: dict, cidade_normalizada: str, bairro: str | None) -> dict | None:
    try:
        propriedades = _propriedades(ad)
        preco = _preco_rsc(ad)
        area = _extrair_float(re.search(r"(\d+(?:[,.]\d+)?)\s*m[²2]", propriedades.get("size", "")))
        if preco is None or area is None or area <= 0:
            return None

        nome = str(ad.get("subject") or "Sem título").strip()
        localizacao = str(ad.get("location") or "").strip()
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


def parse_olx_html(
    html: str,
    cidade_normalizada: str,
    exigir_municipio: bool = False,
    descartes: Counter | None = None,
) -> list[dict]:
    """
    Anúncio de outro município é sempre descartado — a média de Fortaleza não
    pode levar Caucaia junto. Anúncio que não declara município só passa quando
    a página já veio filtrada pela cidade no path (`exigir_municipio=False`).
    `descartes` recebe a contagem por município, para o diagnóstico.
    """
    descartes = descartes if descartes is not None else Counter()
    ads_rsc = _extrair_ads_rsc(html)
    if ads_rsc:
        alvo = _chave_cidade(cidade_normalizada)
        resultados = []
        fora = 0
        for ad in ads_rsc:
            municipio, bairro = _municipio_e_bairro(ad, cidade_normalizada)
            if municipio is None:
                if exigir_municipio:
                    descartes["(sem município)"] += 1
                    fora += 1
                    continue
            elif _chave_cidade(municipio) != alvo:
                descartes[municipio] += 1
                fora += 1
                continue
            item = _parse_ad_rsc(ad, cidade_normalizada, bairro)
            if item:
                resultados.append(item)
                if municipio is not None:
                    _aprender_regiao(item["url_anuncio"], cidade_normalizada)
        logger.info(
            f"OLX: {len(resultados)}/{len(ads_rsc)} anúncios válidos no payload RSC"
            + (f" ({fora} de outro município ou sem município)" if fora else "")
        )
        return resultados

    if exigir_municipio:
        # Os cards HTML antigos não trazem o município de forma confiável: na
        # busca por texto no estado, melhor nada do que outra cidade.
        return []

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
    bairro: str | None = None,
) -> list[dict]:
    """
    Tenta, em ordem de precisão: bairro no path → cidade no path → texto no
    estado. A página 1 decide o modo; as demais seguem nele via `paginar`.

    Cai para o modo seguinte quando a página não abre (404, bloqueio). A cidade
    também cai quando abre vazia — URL de região errada costuma abrir sem
    anúncio, e uma requisição a mais é barata perto de perder o portal. O
    bairro vazio NÃO cai: sem oferta no bairro, a cidade inteira seria só
    ruído para o filtro de bairro descartar depois.
    """
    cidade_normalizada = normalizar_cidade(cidade.split(',')[0])
    descartes: Counter = Counter()
    regiao = regiao_olx(estado, cidade)

    modos: list[tuple[str, dict]] = []
    if regiao:
        if bairro:
            modos.append(("bairro", {"bairro": bairro, "por_cidade": True}))
        modos.append(("cidade", {"por_cidade": True}))
    modos.append(("estado", {"por_cidade": False}))

    def montar(opcoes: dict, pagina: int) -> str:
        return build_olx_url(cidade, estado, preco_min, preco_max, quartos, pagina=pagina, **opcoes)

    async def ler(url: str, rotulo: str, exigir_municipio: bool) -> list[dict] | None:
        """None = a página não abriu; [] = abriu sem anúncio da cidade."""
        logger.info(f"Scraping OLX {rotulo}: {url}")
        try:
            html = await buscar_html(url, "OLX")
        except Exception as e:
            logger.error(f"OLX {rotulo}: erro no scraping: {e}")
            return None
        if not html or len(html) < 1000:
            logger.warning(f"OLX {rotulo}: resposta vazia ou muito curta")
            return None
        return parse_olx_html(html, cidade_normalizada, exigir_municipio, descartes)

    modo, opcoes, primeira = modos[-1][0], modos[-1][1], None
    for modo, opcoes in modos:
        primeira = await ler(montar(opcoes, 1), f"p1 ({modo})", modo == "estado")
        if primeira or (modo == "bairro" and primeira is not None):
            break
        if modo == "cidade" and primeira is None:
            _esquecer_regiao(estado, cidade)

    exigir = modo == "estado"

    async def buscar_pagina(pagina: int) -> list[dict]:
        if pagina == 1:
            return primeira or []
        return await ler(montar(opcoes, pagina), f"p{pagina} ({modo})", exigir) or []

    resultados = await paginar(buscar_pagina, MAX_PAGINAS_OLX, "OLX") if primeira else []

    ULTIMA_COLETA.clear()
    ULTIMA_COLETA.update({
        "modo": modo,
        "url_p1": montar(opcoes, 1),
        "regiao": regiao_olx(estado, cidade),
        "anuncios": len(resultados),
        "descartados_outro_municipio": dict(descartes.most_common()),
    })
    if descartes:
        logger.info(f"OLX ({modo}): descartados por município: {dict(descartes.most_common(5))}")
    return resultados
