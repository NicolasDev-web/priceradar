"""Aprofundamento seletivo da identidade em páginas de anúncios."""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from repositories.identidade_cache_repo import gravar_cache, ler_cache
from scraper.http import buscar_html
from scraper.parser import extrair_nome_empreendimento

PORTAIS_SUPORTADOS = {"olx", "vivareal", "zap", "zapimoveis", "imovelweb", "chavesnamao"}
MAX_DETALHES = 12
MAX_POR_PORTAL = 4
ORCAMENTO_SEGUNDOS = 30
VALIDADE = timedelta(days=30)


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    itens: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            valor = json.loads(tag.string or tag.get_text() or "null")
        except (TypeError, ValueError):
            continue
        fila = valor if isinstance(valor, list) else [valor]
        for dado in fila:
            if isinstance(dado, dict) and isinstance(dado.get("@graph"), list):
                fila.extend(dado["@graph"])
            elif isinstance(dado, dict):
                itens.append(dado)
    return itens


def _valor_profundo(obj, chaves: set[str]):
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave.lower() in chaves and isinstance(valor, (str, int, float)) and str(valor).strip():
                return str(valor).strip()
        for valor in obj.values():
            achado = _valor_profundo(valor, chaves)
            if achado:
                return achado
    elif isinstance(obj, list):
        for valor in obj:
            achado = _valor_profundo(valor, chaves)
            if achado:
                return achado
    return None


def extrair_detalhe(html: str, portal: str) -> dict:
    """JSON-LD primeiro; estado JSON e metatags são fallbacks dos cinco portais."""
    soup = BeautifulSoup(html, "lxml")
    dados = _jsonld(soup)
    titulo = descricao = endereco = bairro = nome = None
    lat = lng = None
    for dado in dados:
        titulo = titulo or dado.get("name") or dado.get("headline")
        descricao = descricao or dado.get("description")
        end = dado.get("address")
        if isinstance(end, str):
            endereco = endereco or end
        elif isinstance(end, dict):
            endereco = endereco or end.get("streetAddress")
            bairro = bairro or end.get("addressLocality")
        geo = dado.get("geo")
        if isinstance(geo, dict):
            lat = lat or geo.get("latitude")
            lng = lng or geo.get("longitude")
    # RSC/__NEXT_DATA__/estado de Redux dos portais. O fallback só preenche
    # campos ausentes e não substitui um valor estruturado.
    estados: list[object] = []
    for tag in soup.find_all("script"):
        identificador = tag.get("id", "")
        texto = tag.string or ""
        if identificador == "__NEXT_DATA__" or (texto.lstrip().startswith(("{", "[")) and len(texto) > 30):
            try:
                estados.append(json.loads(texto))
            except (TypeError, ValueError):
                pass
    for estado in estados:
        endereco = endereco or _valor_profundo(estado, {"streetaddress", "address", "endereco"})
        bairro = bairro or _valor_profundo(estado, {"neighborhood", "bairro"})
        descricao = descricao or _valor_profundo(estado, {"description", "descricao"})
        titulo = titulo or _valor_profundo(estado, {"title", "name", "titulo"})
        nome = nome or _valor_profundo(estado, {"developmentname", "condominiumname", "nomeempreendimento"})
    def meta(prop: str):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag.get("content") if tag else None
    titulo = titulo or meta("og:title")
    descricao = descricao or meta("og:description") or meta("description")
    texto_nome = " ".join(str(v) for v in (nome, titulo, descricao) if v)
    nome = nome or extrair_nome_empreendimento(texto_nome)
    if not endereco:
        texto = " ".join(soup.get_text(" ", strip=True).split())
        m = re.search(r"\b((?:Rua|R\.|Avenida|Av\.|Travessa|Alameda)\s+[^,;|]{3,70}(?:[,\s]+\d{1,6})?)\b", texto, re.I)
        endereco = m.group(1).strip() if m else None
    resultado = {
        "nome_anuncio": str(titulo).strip() if titulo else None,
        "nome_empreendimento": str(nome).strip() if nome else None,
        "descricao": str(descricao).strip() if descricao else None,
        "endereco": str(endereco).strip() if endereco else None,
        "bairro": str(bairro).strip() if bairro else None,
        "latitude": float(lat) if lat not in (None, "") else None,
        "longitude": float(lng) if lng not in (None, "") else None,
        "fonte": f"detalhe:{portal}",
    }
    resultado["proveniencia"] = {
        campo: resultado["fonte"] for campo in ("nome_empreendimento", "endereco") if resultado.get(campo)
    }
    return resultado


def _precisa(item: dict) -> bool:
    return not item.get("nome_empreendimento") or not item.get("endereco") or not item.get("descricao")


def selecionar_candidatos(itens: list[dict]) -> list[dict]:
    contagem: Counter[str] = Counter()
    saida = []
    # Mais campos faltantes primeiro; garante que o orçamento beneficie quem
    # pode mudar de classe com o detalhe.
    ordenados = sorted(itens, key=lambda i: sum(not i.get(c) for c in
        ("nome_empreendimento", "endereco", "descricao")), reverse=True)
    for item in ordenados:
        portal = str(item.get("portal") or "").lower()
        url = str(item.get("url_anuncio") or "")
        if portal not in PORTAIS_SUPORTADOS or urlparse(url).scheme not in {"http", "https"} or not _precisa(item):
            continue
        if contagem[portal] >= MAX_POR_PORTAL:
            continue
        contagem[portal] += 1
        saida.append(item)
        if len(saida) >= MAX_DETALHES:
            break
    return saida


async def _buscar_um(item: dict, diagnostico: dict) -> tuple[dict, dict | None]:
    url = item["url_anuncio"]
    portal = str(item.get("portal") or "").lower()
    try:
        html = await buscar_html(url, f"detalhe_{portal}")
    except Exception as exc:
        diagnostico["falhas_por_fonte"][portal] = type(exc).__name__
        return item, None
    if not html:
        diagnostico["falhas_por_fonte"][portal] = "indisponivel"
        return item, None
    detalhe = extrair_detalhe(html, portal)
    return item, detalhe


async def enriquecer_candidatos(db, itens: list[dict], diagnostico: dict) -> list[dict]:
    candidatos = selecionar_candidatos(itens)
    diagnostico["candidatos_detalhe"] = len(candidatos)
    if not candidatos:
        return itens
    pares: list[tuple[dict, dict | None]] = []
    sem_cache: list[dict] = []
    # AsyncSession não admite operações concorrentes; cache é lido antes das
    # requisições paralelas e gravado depois delas.
    for item in candidatos:
        em_cache = await ler_cache(db, "anuncio_detalhe", item["url_anuncio"])
        if em_cache:
            diagnostico["acertos_cache"] += 1
            pares.append((item, em_cache["payload"]))
        else:
            sem_cache.append(item)
    tarefas = [asyncio.create_task(_buscar_um(item, diagnostico)) for item in sem_cache]
    try:
        if tarefas:
            pares.extend(await asyncio.wait_for(asyncio.gather(*tarefas), timeout=ORCAMENTO_SEGUNDOS))
    except asyncio.TimeoutError:
        for tarefa in tarefas:
            tarefa.cancel()
        diagnostico["falhas_por_fonte"]["detalhes"] = "timeout_30s"
        pares.extend(t.result() for t in tarefas if t.done() and not t.cancelled() and not t.exception())
    for item, detalhe in pares:
        if not detalhe:
            continue
        diagnostico["detalhes_lidos"] += 1
        if item in sem_cache:
            portal = str(item.get("portal") or "").lower()
            await gravar_cache(db, "anuncio_detalhe", item["url_anuncio"], portal,
                               item["url_anuncio"], detalhe, VALIDADE)
        mudou = False
        fontes = set(item.get("fontes_identidade") or [])
        fontes.add(f"listagem:{item.get('portal') or 'desconhecido'}")
        for campo in ("nome_anuncio", "nome_empreendimento", "descricao", "endereco", "bairro",
                      "latitude", "longitude"):
            if not item.get(campo) and detalhe.get(campo) not in (None, ""):
                item[campo] = detalhe[campo]
                mudou = True
        if mudou:
            fontes.add(detalhe.get("fonte") or f"detalhe:{item.get('portal')}")
            item["fontes_identidade"] = sorted(fontes)
            if detalhe.get("latitude") is not None and not item.get("origem_coordenada"):
                item["origem_coordenada"] = "exata"
    return itens

