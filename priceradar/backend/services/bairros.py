"""Sugestão de bairros por cidade.

O VivaReal publica, na própria página de resultados, links para as buscas
filtradas por bairro (`/venda/{estado}/{cidade}/bairros/{slug}/`). São os
bairros com oferta de fato naquela praça — melhor que uma lista genérica de
divisões administrativas, porque bairro sem anúncio não serve para comparar
preço.

Cache em memória: a lista de bairros de uma cidade não muda de um dia para o
outro, e sem cache cada tecla digitada dispararia uma requisição ao portal.
"""
from __future__ import annotations

import asyncio
import logging
import re

from scraper.http import buscar_html
from scraper.vivareal import _extrair_estado_cidade

logger = logging.getLogger(__name__)

# Páginas varridas para montar a lista. A 1ª já traz ~15 bairros; a 2ª
# acrescenta alguns sem custo relevante (acesso direto, sem cota).
_PAGINAS = 2

_cache: dict[str, list[str]] = {}


def _slug_para_nome(slug: str) -> str:
    """`sao-joao-do-tauape` → `São João do Tauape` (sem acento; é sugestão)."""
    minusculas = {"do", "da", "de", "dos", "das", "e"}
    partes = slug.split("-")
    return " ".join(
        p if p in minusculas and i > 0 else p.capitalize()
        for i, p in enumerate(partes)
    )


async def listar_bairros(cidade_str: str) -> list[str]:
    """
    Bairros com oferta na cidade, em ordem alfabética.

    Devolve lista vazia se o portal não responder — a sugestão é conveniência,
    e o campo de bairro continua aceitando qualquer texto digitado.
    """
    chave = cidade_str.strip().lower()
    if chave in _cache:
        return _cache[chave]

    estado, cidade = _extrair_estado_cidade(cidade_str)
    if not cidade:
        return []

    async def _pagina(n: int) -> str | None:
        url = f"https://www.vivareal.com.br/venda/{estado}/{cidade}/apartamento_residencial/"
        if n > 1:
            url += f"?pagina={n}"
        return await buscar_html(url, f"Bairros {cidade} p{n}")

    paginas = await asyncio.gather(
        *(_pagina(n) for n in range(1, _PAGINAS + 1)), return_exceptions=True
    )

    padrao = re.compile(rf"/venda/{re.escape(estado)}/{re.escape(cidade)}/bairros/([a-z0-9-]+)/")
    slugs: set[str] = set()
    for html in paginas:
        if isinstance(html, str):
            slugs.update(padrao.findall(html))

    bairros = sorted(_slug_para_nome(s) for s in slugs)
    if bairros:
        _cache[chave] = bairros
    logger.info(f"Bairros de {cidade_str}: {len(bairros)} encontrados")
    return bairros
