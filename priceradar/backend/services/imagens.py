"""Proxy das fotos dos anúncios, com cache em disco — F1.9 do PLANO_MELHORIAS.md.

O card carrega a foto direto do CDN do portal. Isso falha em dois casos:
- a rede de quem abre o app bloqueia o CDN (filtro corporativo);
- o CDN recusa o pedido por não vir do próprio portal (hotlink).
Nos dois, o card pede a mesma foto aqui, e o backend — que está numa rede que
alcança os portais, senão nem teria coletado — baixa e devolve.

Um endpoint que busca URL arbitrária é SSRF de manual. Por isso:
- só https, só hosts dos portais (lista fechada, casando sufixo com ponto);
- sem seguir redirecionamento para fora da lista;
- só devolve o que é imagem, até um tamanho máximo;
- exige o token de sessão (checado na rota).
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Domínios de onde os scrapers tiram foto. Casamento por sufixo com ponto:
# "img.olx.com.br" passa por "olx.com.br"; "olx.com.br.evil.com" não.
HOSTS_PERMITIDOS = (
    "vivareal.com", "vivareal.com.br", "zapimoveis.com", "zapimoveis.com.br", "grupozap.com",
    "chavesnamao.com.br", "imovelweb.com.br", "imovelwebcdn.com", "olx.com.br", "olxcdn.com",
    "quintoandar.com.br", "mlstatic.com", "mercadolivre.com.br", "netimoveis.com",
)

TAMANHO_MAX = 8 * 1024 * 1024          # foto de anúncio passa longe disso
VALIDADE_SEGUNDOS = 7 * 24 * 60 * 60   # anúncio muda de foto raramente
MAX_REDIRECIONAMENTOS = 3

_CACHE_DIR = Path(os.getenv("IMAGENS_CACHE_DIR") or Path(__file__).resolve().parents[1] / "data" / "imagens")
_client: httpx.AsyncClient | None = None


class ImagemIndisponivel(Exception):
    pass


def url_permitida(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return False
    host = p.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False                     # IP literal nunca: é o atalho clássico para a rede interna
    except ValueError:
        pass
    if p.port not in (None, 443):
        return False
    return any(host == d or host.endswith("." + d) for d in HOSTS_PERMITIDOS)


def _caminho(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()
    return _CACHE_DIR / h[:2] / h


def _ler_cache(caminho: Path) -> tuple[bytes, str] | None:
    try:
        if time.time() - caminho.stat().st_mtime > VALIDADE_SEGUNDOS:
            return None
        tipo = caminho.with_suffix(".tipo").read_text()
        return caminho.read_bytes(), tipo
    except OSError:
        return None


def _gravar_cache(caminho: Path, conteudo: bytes, tipo: str) -> None:
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.with_suffix(".tipo").write_text(tipo)
        tmp = caminho.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(conteudo)
        tmp.replace(caminho)
    except OSError as e:
        logger.debug(f"Imagens: não gravou cache: {e}")


def _cliente() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # Sem seguir redirecionamento automaticamente: cada salto é revalidado.
        _client = httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                    headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    return _client


async def obter_imagem(url: str) -> tuple[bytes, str]:
    """(bytes, content-type) da foto, do cache ou do portal."""
    if not url_permitida(url):
        raise ImagemIndisponivel("host não permitido")
    caminho = _caminho(url)
    em_cache = _ler_cache(caminho)
    if em_cache:
        return em_cache

    atual = url
    for _ in range(MAX_REDIRECIONAMENTOS + 1):
        try:
            resp = await _cliente().get(atual)
        except httpx.HTTPError as e:
            raise ImagemIndisponivel(type(e).__name__) from e
        if resp.status_code in (301, 302, 303, 307, 308):
            proximo = urljoin(atual, resp.headers.get("location", ""))
            if not url_permitida(proximo):
                raise ImagemIndisponivel("redirecionou para fora dos portais")
            atual = proximo
            continue
        break
    else:
        raise ImagemIndisponivel("redirecionamentos demais")

    tipo = resp.headers.get("content-type", "").split(";")[0].strip()
    if resp.status_code != 200 or not tipo.startswith("image/") or tipo == "image/svg+xml":
        # SVG fica de fora: pode carregar script.
        raise ImagemIndisponivel(f"portal respondeu {resp.status_code} ({tipo or 'sem tipo'})")
    if len(resp.content) > TAMANHO_MAX:
        raise ImagemIndisponivel("imagem grande demais")

    _gravar_cache(caminho, resp.content, tipo)
    return resp.content, tipo
