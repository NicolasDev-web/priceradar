"""Proxy dos tiles do mapa (CARTO dark_all), com cache em disco.

Por que passar pelo backend em vez de o navegador pedir direto à CARTO:

1. **A chave saía no bundle.** Com `VITE_CARTO_API_KEY` o Vite a embutia no JS
   servido — qualquer um que abrisse o site a lia. Aqui ela fica no `.env` do
   backend e nunca chega ao navegador.
2. **Chave nova exigia rebuild.** O `.bat` serve o `dist/` já compilado: criar
   o `.env.local` depois do build não tinha efeito, e o Dockerfile nem recebia
   a chave. Agora basta reiniciar o backend.
3. **Cota.** O plano grátis tem 5M tiles/mês; com o cache, o mesmo quarteirão
   visto por duas pessoas custa um tile, não dois.

Sem `CARTO_API_KEY` ou com a CARTO fora, a rota responde 503 e o mapa troca
sozinho para um provedor sem chave (ver `Mapa.tsx`).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# O parâmetro é `key`, não `api_key` — a doc da CARTO usa os dois nomes em
# lugares diferentes e só `key` funciona (testado em 28/08/2026).
CARTO_URL = "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png"

# Acima de 20 a CARTO não tem tile; abaixo de 0 não existe.
ZOOM_MAX = 20

# Tile de mapa base quase não muda. 30 dias é longo o bastante para o cache
# valer a pena e curto o bastante para uma rua nova aparecer um dia.
VALIDADE_SEGUNDOS = 30 * 24 * 60 * 60

_CACHE_DIR = Path(
    os.getenv("TILES_CACHE_DIR")
    or Path(__file__).resolve().parents[1] / "data" / "tiles"
)

_client: httpx.AsyncClient | None = None


class TileIndisponivel(Exception):
    """Sem chave, ou a CARTO não entregou o tile. O front cai no fallback."""


def coordenada_valida(z: int, x: int, y: int) -> bool:
    """z/x/y dentro da grade do Web Mercator — nada de URL livre repassada adiante."""
    if not (0 <= z <= ZOOM_MAX):
        return False
    lado = 1 << z
    return 0 <= x < lado and 0 <= y < lado


def _caminho_cache(z: int, x: int, y: int, retina: bool) -> Path:
    return _CACHE_DIR / str(z) / str(x) / f"{y}{'@2x' if retina else ''}.png"


def _ler_cache(caminho: Path) -> bytes | None:
    try:
        if time.time() - caminho.stat().st_mtime > VALIDADE_SEGUNDOS:
            return None
        return caminho.read_bytes()
    except OSError:
        return None


def _gravar_cache(caminho: Path, conteudo: bytes) -> None:
    # Escreve num temporário e renomeia: dois pedidos do mesmo tile ao mesmo
    # tempo nunca deixam um PNG pela metade no cache.
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_suffix(f".{os.getpid()}.{id(conteudo)}.tmp")
        tmp.write_bytes(conteudo)
        tmp.replace(caminho)
    except OSError as e:
        # Cache é economia, não requisito: sem disco o tile ainda é servido.
        logger.debug(f"Tiles: não foi possível gravar cache {caminho}: {e}")


def _cliente() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def obter_tile(z: int, x: int, y: int, retina: bool = False) -> bytes:
    """PNG do tile, do cache ou da CARTO. Levanta TileIndisponivel se não houver."""
    caminho = _caminho_cache(z, x, y, retina)
    em_cache = _ler_cache(caminho)
    if em_cache is not None:
        return em_cache

    # Lida a cada pedido, não no import: trocar a chave no .env e reiniciar
    # é o fluxo esperado, e testes precisam poder mudá-la.
    chave = os.getenv("CARTO_API_KEY", "").strip()
    if not chave:
        raise TileIndisponivel("CARTO_API_KEY não configurada")

    url = CARTO_URL.format(z=z, x=x, y=y, r="@2x" if retina else "")
    try:
        resp = await _cliente().get(url, params={"key": chave})
    except httpx.HTTPError as e:
        raise TileIndisponivel(f"CARTO inacessível: {type(e).__name__}") from e

    tipo = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not tipo.startswith("image/"):
        # Não loga a URL: ela carrega a chave.
        raise TileIndisponivel(f"CARTO respondeu {resp.status_code} ({tipo or 'sem tipo'})")

    _gravar_cache(caminho, resp.content)
    return resp.content
