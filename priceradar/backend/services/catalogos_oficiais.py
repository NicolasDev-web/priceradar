"""Catálogos oficiais usados apenas como referência de identidade.

Os adaptadores são deliberadamente independentes e tolerantes a falhas. Uma
fonte indisponível não interrompe a procura e nenhum valor de preço lido aqui é
devolvido ao restante do sistema.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from repositories.identidade_cache_repo import gravar_cache, ler_cache
from scraper.http import buscar_html
from services.agrupamento import normalizar_nome, similaridade_nome
from services.texto import normalizar

logger = logging.getLogger(__name__)
VALIDADE_LISTAGEM = timedelta(days=7)
VALIDADE_DETALHE = timedelta(days=30)


@dataclass(frozen=True)
class ProvedorOficial:
    nome: str
    construtora: str
    dominio: str
    listagem: str

    def url_listagem(self, cidade_slug: str, uf: str) -> str:
        return self.listagem.format(cidade=cidade_slug, uf=uf.lower())


PROVEDORES = (
    ProvedorOficial("mrv", "MRV", "https://www.mrv.com.br", "https://www.mrv.com.br/imoveis/{uf}/{cidade}"),
    ProvedorOficial("direcional", "Direcional", "https://www.direcional.com.br", "https://www.direcional.com.br/empreendimentos/?cidade={cidade}"),
    ProvedorOficial("tenda", "Tenda", "https://tenda.com", "https://tenda.com/apartamentos-a-venda/{uf}/{cidade}"),
    ProvedorOficial("cury", "Cury", "https://cury.net", "https://cury.net/imoveis?cidade={cidade}"),
)


def _cidade(cidade: str) -> tuple[str, str, str]:
    partes = [p.strip() for p in cidade.split(",")]
    nome = partes[0]
    uf = partes[1] if len(partes) > 1 else ""
    slug = re.sub(r"[^a-z0-9]+", "-", normalizar(nome)).strip("-")
    return nome, uf, slug


def _nome_catalogo_compativel(candidato: str | None, alvo: str) -> bool:
    """Exige os tokens distintivos; a similaridade de caracteres aceita falsos positivos curtos.

    ``normalizar_nome`` já remove termos genéricos como "Parque" e
    "Residencial", então Parque Marista compara pela palavra distintiva
    ``marista``. Nomes de um token precisam de igualdade exata.
    """
    nome = normalizar_nome(candidato)
    termos = set(alvo.split())
    encontrados = set(nome.split()) if nome else set()
    if not termos or not encontrados:
        return False
    if termos <= encontrados:
        return True
    return len(termos) >= 2 and similaridade_nome(nome, alvo) >= .9 \
        and bool(termos & encontrados)


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    saida: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            valor = json.loads(tag.string or tag.get_text() or "null")
        except (TypeError, ValueError):
            continue
        fila = valor if isinstance(valor, list) else [valor]
        for item in fila:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                fila.extend(item["@graph"])
            elif isinstance(item, dict):
                saida.append(item)
    return saida


def extrair_links_listagem(html: str, base: str) -> list[dict]:
    """Extrai pares nome/URL. Aceita cards HTML e ItemList em JSON-LD."""
    soup = BeautifulSoup(html, "lxml")
    candidatos: dict[str, dict] = {}
    for dado in _jsonld(soup):
        itens = dado.get("itemListElement") or []
        for entrada in itens if isinstance(itens, list) else []:
            item = entrada.get("item", entrada) if isinstance(entrada, dict) else {}
            if isinstance(item, str):
                item = {"url": item}
            url = item.get("url") if isinstance(item, dict) else None
            nome = item.get("name") if isinstance(item, dict) else None
            if url and nome:
                candidatos[urljoin(base, url)] = {"nome": str(nome).strip(), "url": urljoin(base, url)}
    for a in soup.find_all("a", href=True):
        nome = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(base, a["href"])
        if len(nome) >= 4 and href.startswith(base):
            candidatos.setdefault(href, {"nome": nome, "url": href})
    return list(candidatos.values())


def _endereco_jsonld(dados: list[dict]) -> tuple[str | None, str | None, str | None]:
    for dado in dados:
        end = dado.get("address")
        if isinstance(end, str):
            return end, None, None
        if isinstance(end, dict):
            rua = end.get("streetAddress")
            bairro = end.get("addressLocality") or end.get("addressRegion")
            cidade = end.get("addressLocality")
            if rua or bairro:
                return rua, bairro, cidade
    return None, None, None


def extrair_referencia_detalhe(
    html: str, *, provedor: ProvedorOficial, url: str, nome_listagem: str, cidade: str,
) -> dict:
    """Lê identidade canônica sem sequer expor ofertas/preços do documento."""
    soup = BeautifulSoup(html, "lxml")
    dados = _jsonld(soup)
    nomes = [str(d.get("name")).strip() for d in dados if d.get("name")]
    h1 = soup.find("h1")
    if h1:
        nomes.insert(0, " ".join(h1.get_text(" ", strip=True).split()))
    nome = next((n for n in nomes if len(n) >= 4), nome_listagem)
    endereco, bairro, cidade_ld = _endereco_jsonld(dados)
    texto = " ".join(soup.get_text(" ", strip=True).split())
    if not endereco:
        # Fallback conservador: exige logradouro e número; evita guardar frases.
        m = re.search(r"\b((?:Rua|R\.|Avenida|Av\.|Travessa|Alameda)\s+[^,;|]{3,70}[,\s]+\d{1,6})\b", texto, re.I)
        endereco = m.group(1).strip() if m else None
    if not bairro:
        meta = soup.find("meta", attrs={"name": re.compile("bairro|neighbou?rhood", re.I)})
        bairro = meta.get("content") if meta else None
    aliases = []
    for n in [nome_listagem, *nomes]:
        if n and normalizar_nome(n) != normalizar_nome(nome) and n not in aliases:
            aliases.append(n)
    return {
        "nome": nome,
        "aliases": aliases,
        "construtora": provedor.construtora,
        "endereco": endereco,
        "bairro": bairro,
        "cidade": cidade_ld or cidade.split(",")[0].strip(),
        "fonte": provedor.nome,
        "url": url,
        "proveniencia": {
            "nome": f"catalogo:{provedor.nome}",
            "endereco": f"catalogo:{provedor.nome}" if endereco else None,
        },
    }


async def _listagem(db, provedor: ProvedorOficial, cidade: str, diagnostico: dict) -> list[dict]:
    nome_cidade, uf, slug = _cidade(cidade)
    chave = f"{provedor.nome}:{normalizar(cidade)}"
    em_cache = await ler_cache(db, "oficial_listagem", chave)
    if em_cache:
        diagnostico["acertos_cache"] += 1
        return em_cache["payload"]
    url = provedor.url_listagem(slug, uf)
    try:
        html = await buscar_html(url, f"oficial_{provedor.nome}")
    except Exception as exc:  # uma construtora nunca derruba a procura
        diagnostico["falhas_por_fonte"][provedor.nome] = type(exc).__name__
        return []
    if not html:
        diagnostico["falhas_por_fonte"][provedor.nome] = "indisponivel"
        return []
    itens = extrair_links_listagem(html, provedor.dominio)
    await gravar_cache(db, "oficial_listagem", chave, provedor.nome, url, itens, VALIDADE_LISTAGEM)
    return itens


async def buscar_referencia_oficial(db, cidade: str, nome: str | None, diagnostico: dict) -> dict | None:
    if not nome or not normalizar_nome(nome):
        return None
    alvo = normalizar_nome(nome)
    escolhas: list[tuple[float, ProvedorOficial, dict]] = []
    inicio = time.monotonic()
    for provedor in PROVEDORES:
        restante = 20.0 - (time.monotonic() - inicio)
        if restante <= 0:
            diagnostico["falhas_por_fonte"]["catalogos_oficiais"] = "timeout_20s"
            break
        try:
            listagem = await asyncio.wait_for(_listagem(db, provedor, cidade, diagnostico),
                                              timeout=min(8.0, restante))
        except asyncio.TimeoutError:
            diagnostico["falhas_por_fonte"][provedor.nome] = "timeout"
            continue
        for item in listagem:
            nome_item = normalizar_nome(item.get("nome"))
            nota = similaridade_nome(nome_item, alvo)
            if _nome_catalogo_compativel(nome_item, alvo):
                escolhas.append((nota, provedor, item))
    for _, provedor, item in sorted(escolhas, key=lambda x: x[0], reverse=True):
        url = item["url"]
        chave = f"{provedor.nome}:{url}"
        em_cache = await ler_cache(db, "oficial_detalhe", chave)
        if em_cache:
            diagnostico["acertos_cache"] += 1
            referencia = em_cache["payload"]
        else:
            try:
                restante = max(.1, 20.0 - (time.monotonic() - inicio))
                html = await asyncio.wait_for(buscar_html(url, f"oficial_{provedor.nome}"),
                                              timeout=min(8.0, restante))
            except asyncio.TimeoutError:
                diagnostico["falhas_por_fonte"][provedor.nome] = "timeout"
                continue
            except Exception as exc:
                diagnostico["falhas_por_fonte"][provedor.nome] = type(exc).__name__
                continue
            if not html:
                diagnostico["falhas_por_fonte"][provedor.nome] = "detalhe_indisponivel"
                continue
            referencia = extrair_referencia_detalhe(
                html, provedor=provedor, url=url, nome_listagem=item["nome"], cidade=cidade,
            )
            await gravar_cache(db, "oficial_detalhe", chave, provedor.nome, url,
                               referencia, VALIDADE_DETALHE)
        nomes = [referencia.get("nome"), *(referencia.get("aliases") or [])]
        if any(_nome_catalogo_compativel(n, alvo) for n in nomes if n):
            return referencia
    return None

