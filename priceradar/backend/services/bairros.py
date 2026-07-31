"""Sugestão de bairros por cidade.

São os bairros com oferta de fato na praça — melhor que uma lista genérica de
divisões administrativas, porque bairro sem anúncio não serve para comparar
preço.

Três fontes, em ordem de qualidade:

1. **O payload RSC do VivaReal** (`neighborhood` por anúncio). Nome estruturado
   e acentuado: "Aracapé", "Cocó", "Parquelândia".
2. **Os links `/venda/{estado}/{cidade}/bairros/{slug}/`** da própria página.
   Só dão o slug, sem acento — servem para completar o que o RSC não cobriu.
3. **O que as buscas reais já viram**, acumulado em disco. A lista melhora com
   o uso.

Medido em 30/07/2026, acumulando por página:

    Fortaleza   slug: 15 na p1 e ainda 15 na p5   RSC: 18 → 43   união: 58
    Caucaia     slug: 15 na p1 e ainda 15 na p5   RSC: 15 → 32   união: 47
    Parnaíba/PI slug:  3                          RSC:  5        união:  8

O bloco de links `/bairros/` é uma sidebar fixa: satura em 15 e **não cresce**
com mais páginas — varrer mais páginas só ajuda por causa do RSC. Parnaíba com
8 é limite real de estoque da praça, não falha de coleta.

O cache é persistido porque, em memória, ele evaporava a cada restart e a
primeira busca do dia pagava as quatro requisições de novo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import re
import unicodedata

from scraper.http import buscar_html
from scraper.rsc_grupozap import _payload_rsc
from scraper.vivareal import _extrair_estado_cidade

logger = logging.getLogger(__name__)

# 4 páginas: é o joelho da curva medida acima — a 5ª acrescentou 0 bairro em
# Fortaleza e 1 em Caucaia. Cada página é uma requisição direta (curl-cffi),
# grátis e sob o semáforo de 3 por host.
_PAGINAS = int(os.getenv("BAIRROS_PAGINAS", "4"))

_CACHE_PATH = pathlib.Path(os.getenv(
    "BAIRROS_CACHE_PATH",
    str(pathlib.Path(__file__).parent.parent / "data" / "bairros_por_cidade.json"),
))

_NEIGHBORHOOD = re.compile(r'"neighborhood":"([^"]*)"')

# "Área Rural de Caucaia" é uma categoria residual do portal, não um bairro que
# alguém compare para precificar.
_NAO_E_BAIRRO = re.compile(r"^[áa]rea rural\b", re.IGNORECASE)

_cache: dict[str, list[str]] = {}


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _tem_acento(texto: str) -> bool:
    """Compara preservando a caixa — `_normalizar` também baixa a caixa, e usá-lo
    aqui faria todo nome capitalizado parecer acentuado."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return any(unicodedata.combining(c) for c in nfkd)


def _slug_para_nome(slug: str) -> str:
    """`sao-joao-do-tauape` → `Sao Joao do Tauape`.

    Fallback: não reacentua, porque a informação não está no slug. Só entra
    quando o RSC não trouxe aquele bairro com o nome de verdade.
    """
    minusculas = {"do", "da", "de", "dos", "das", "e"}
    partes = slug.split("-")
    return " ".join(
        p if p in minusculas and i > 0 else p.capitalize()
        for i, p in enumerate(partes)
    )


def _unir(*fontes: list[str]) -> list[str]:
    """
    Une as fontes sem repetir, preferindo a grafia acentuada.

    "Cocó" (RSC) e "Coco" (slug) são o mesmo bairro. A comparação ignora acento
    e caixa; entre duas grafias equivalentes fica a que tem acento — é a que o
    usuário reconhece.
    """
    escolhido: dict[str, str] = {}
    for fonte in fontes:
        for nome in fonte:
            nome = nome.strip()
            if not nome or _NAO_E_BAIRRO.match(nome):
                continue
            chave = _normalizar(nome)
            atual = escolhido.get(chave)
            if atual is None or (_normalizar(atual) == atual and nome != _normalizar(nome)):
                escolhido[chave] = nome
    return sorted(escolhido.values())


def _carregar_cache() -> dict[str, list[str]]:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Cache de bairros corrompido: {e}")
    return {}


def _salvar_cache(dados: dict[str, list[str]]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"Não foi possível salvar o cache de bairros: {e}")


def registrar_bairros_vistos(cidade_str: str, bairros: list[str]) -> None:
    """
    Soma ao cache os bairros que uma busca real encontrou.

    Chamado ao fim de cada busca: o que a coleta viu é, por definição, bairro
    com oferta — e agora vem acentuado, vindo do payload dos portais.
    """
    nomes = [b for b in bairros if b and b.strip()]
    if not nomes:
        return

    chave = cidade_str.strip().lower()
    disco = _carregar_cache()
    unido = _unir(disco.get(chave, []), _cache.get(chave, []), nomes)
    if unido != disco.get(chave):
        disco[chave] = unido
        _salvar_cache(disco)
    _cache[chave] = unido


async def listar_bairros(cidade_str: str) -> list[str]:
    """
    Bairros com oferta na cidade, em ordem alfabética.

    Devolve o que houver em cache se o portal não responder — a sugestão é
    conveniência, e o campo de bairro continua aceitando qualquer texto.
    """
    chave = cidade_str.strip().lower()
    if chave in _cache:
        return _cache[chave]

    do_disco = _carregar_cache().get(chave, [])
    if do_disco:
        _cache[chave] = do_disco
        return do_disco

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

    padrao_slug = re.compile(
        rf"/venda/{re.escape(estado)}/{re.escape(cidade)}/bairros/([a-z0-9-]+)/"
    )
    slugs: set[str] = set()
    do_rsc: set[str] = set()
    for html in paginas:
        if not isinstance(html, str):
            continue
        slugs.update(padrao_slug.findall(html))
        do_rsc.update(n for n in _NEIGHBORHOOD.findall(_payload_rsc(html)) if n)

    bairros = _unir(sorted(do_rsc), [_slug_para_nome(s) for s in sorted(slugs)])
    if bairros:
        _cache[chave] = bairros
        disco = _carregar_cache()
        disco[chave] = bairros
        _salvar_cache(disco)

    logger.info(
        f"Bairros de {cidade_str}: {len(bairros)} "
        f"({len(do_rsc)} do payload, {len(slugs)} dos links)"
    )
    return bairros
