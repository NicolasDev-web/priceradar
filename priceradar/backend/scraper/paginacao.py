"""Paginação em lotes com parada antecipada — F4.3 do PLANO_MELHORIAS.md.

Antes, cada scraper disparava TODAS as páginas de uma vez (o ChavesNaMão, 12),
mesmo quando o inventário acabava na 4ª: as oito seguintes eram requisição
jogada fora, e requisição a mais é o que os portais pontuam como robô.

Agora as páginas saem em lotes do tamanho do teto de conexões por host
(`MAX_SIMULTANEAS_POR_HOST`, em `http.py` — mais que isso ficaria na fila do
semáforo de qualquer jeito), e a paginação para quando um lote inteiro não
traz nenhum anúncio novo.

Por que o LOTE e não a página: o que cada página devolve já passou pelo filtro
de preço/quartos do scraper. Uma página sem nenhum válido não prova que o
inventário acabou — a seguinte pode ter. Um lote inteiro sem nada novo prova
bem melhor, e cobre também o portal que, passado o fim, devolve a página 1 de
novo (tudo repetido = nada novo).

Com a parada antecipada, subir o teto de páginas de um portal custa pouco
quando o inventário é curto — mas o teto só deve subir depois de medir
(`scripts/diagnosticar_fotos.py`), regra do plano.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

TAMANHO_LOTE = max(1, int(os.getenv("MAX_SIMULTANEAS_POR_HOST", "3")))


def _chave(item: dict) -> str | None:
    url = (item.get("url_anuncio") or "").split("?")[0].split("#")[0].rstrip("/")
    return url or None


async def paginar(
    buscar_pagina: Callable[[int], Awaitable[list[dict] | None]],
    max_paginas: int,
    portal: str,
    tamanho_lote: int = TAMANHO_LOTE,
) -> list[dict]:
    """
    Chama `buscar_pagina(1..max_paginas)` em lotes e devolve os anúncios sem
    repetição (por URL), na ordem das páginas.

    Página que levanta exceção ou devolve None conta como vazia — um erro numa
    página não derruba as outras, como já era com `gather(return_exceptions)`.
    """
    vistos: set[str] = set()
    resultados: list[dict] = []
    ultima = 0

    for inicio in range(1, max_paginas + 1, tamanho_lote):
        paginas = list(range(inicio, min(inicio + tamanho_lote, max_paginas + 1)))
        lote = await asyncio.gather(*(buscar_pagina(p) for p in paginas), return_exceptions=True)
        ultima = paginas[-1]

        novos = 0
        for p, itens in zip(paginas, lote):
            if isinstance(itens, BaseException):
                logger.warning(f"{portal} p{p}: {type(itens).__name__}: {itens}")
                continue
            for item in itens or []:
                chave = _chave(item)
                if chave is None:
                    resultados.append(item)
                    novos += 1
                elif chave not in vistos:
                    vistos.add(chave)
                    resultados.append(item)
                    novos += 1

        if novos == 0:
            if ultima < max_paginas:
                logger.info(f"{portal}: páginas {paginas[0]}-{ultima} sem anúncio novo — parando "
                            f"(economizou {max_paginas - ultima} de {max_paginas} páginas)")
            break

    logger.info(f"{portal}: {len(resultados)} anúncios únicos em {ultima} páginas (teto {max_paginas})")
    return resultados
