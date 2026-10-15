"""Geocodificação do endereço que o USUÁRIO digita na busca por empreendimento.

Usado só para isso — nunca para anúncio coletado. O módulo `geo.py` explica
por que geocodificar anúncio não compensa (ChavesNaMão e ImovelWeb quase não
trazem logradouro). Aqui é uma chamada por pergunta do usuário, com cache em
disco, e o que se ganha é a coordenada do prédio para achar anúncios do Grupo
ZAP a poucos metros dele — que é o sinal mais forte que a coleta tem.

Nominatim (OpenStreetMap): gratuito, sem chave, com política de uso que exige
no máximo 1 requisição por segundo e um User-Agent que identifique a
aplicação. As duas coisas estão aqui.

Falhar é normal (rede, endereço que o OSM não conhece, rua sem número no
mapa). Quem chama recebe None e compara o endereço só como texto.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import tempfile
import threading
import time

import httpx

from services.texto import normalizar

logger = logging.getLogger(__name__)

NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
# A política do Nominatim pede um User-Agent que identifique a aplicação e um
# contato. `GEOCODING_CONTATO` deixa a instalação pôr o e-mail dela.
USER_AGENT = f"PriceRadar/2.0 ({os.getenv('GEOCODING_CONTATO', 'uso interno')})"
HABILITADO = os.getenv("HABILITAR_GEOCODING", "true").lower() == "true"
INTERVALO_MINIMO_S = 1.0
TIMEOUT_S = 8.0

_CACHE_PATH = pathlib.Path(os.getenv(
    "GEOCODING_CACHE_PATH",
    str(pathlib.Path(__file__).parent.parent / "data" / "geocoding_cache.json"),
))
_LOCK_CACHE = threading.Lock()
_LOCK_TAXA = asyncio.Lock()
_ultima_chamada = 0.0


def _chave(endereco: str, cidade: str) -> str:
    return f"{normalizar(endereco)}|{normalizar(cidade)}"


def _carregar_cache() -> dict[str, dict | None]:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _salvar_cache(dados: dict) -> None:
    """Temporário + `os.replace`, como em services/bairros.py: atômico."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporario = tempfile.mkstemp(dir=str(_CACHE_PATH.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        os.replace(temporario, _CACHE_PATH)
    except OSError as e:
        logger.debug(f"Geocoding: não foi possível gravar o cache: {e}")


def interpretar_resposta(dados: list) -> dict | None:
    """
    Primeiro resultado do Nominatim → `{latitude, longitude, rua, numero,
    bairro, precisa}`. `precisa` só é True quando o OSM achou o NÚMERO: sem
    ele, o ponto é o meio da rua, e usar isso como "o prédio" juntaria todos
    os vizinhos.
    """
    if not dados or not isinstance(dados, list) or not isinstance(dados[0], dict):
        return None
    r = dados[0]
    try:
        lat, lng = float(r["lat"]), float(r["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    end = r.get("address") or {}
    numero = end.get("house_number")
    return {
        "latitude": lat,
        "longitude": lng,
        "rua": end.get("road"),
        "numero": numero,
        "bairro": end.get("suburb") or end.get("neighbourhood") or end.get("quarter"),
        "precisa": bool(numero),
        "descricao": r.get("display_name"),
    }


async def _consultar(endereco: str, cidade: str) -> list:
    """A requisição em si, isolada para os testes trocarem por uma falsa."""
    params = {
        "q": f"{endereco}, {cidade}, Brasil",
        "format": "jsonv2",
        "addressdetails": 1,
        "countrycodes": "br",
        "limit": 1,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(NOMINATIM_URL, params=params)
        resp.raise_for_status()
        return resp.json()


async def geocodificar(endereco: str | None, cidade: str) -> dict | None:
    """Coordenada do endereço digitado, ou None. Nunca levanta exceção."""
    global _ultima_chamada
    if not HABILITADO or not endereco or not endereco.strip():
        return None

    chave = _chave(endereco, cidade)
    with _LOCK_CACHE:
        cache = _carregar_cache()
    if chave in cache:
        return cache[chave]

    async with _LOCK_TAXA:
        espera = INTERVALO_MINIMO_S - (time.monotonic() - _ultima_chamada)
        if espera > 0:
            await asyncio.sleep(espera)
        try:
            resultado = interpretar_resposta(await _consultar(endereco, cidade))
        except Exception as e:  # rede, 429, JSON inválido: cai para texto
            logger.info(f"Geocoding falhou para '{endereco}': {e}")
            return None  # não grava: falha de rede não é "endereço inexistente"
        finally:
            _ultima_chamada = time.monotonic()

    # "Não encontrado" também vai para o cache: perguntar de novo dá o mesmo.
    with _LOCK_CACHE:
        cache = _carregar_cache()
        cache[chave] = resultado
        _salvar_cache(cache)
    return resultado
