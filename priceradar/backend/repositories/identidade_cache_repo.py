"""Persistência do cache de identidade de anúncios e catálogos oficiais."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select

from database.models_db import CacheIdentidade


async def ler_cache(db, tipo: str, chave: str, agora: datetime | None = None) -> dict | None:
    agora = agora or datetime.utcnow()
    entrada = await db.scalar(select(CacheIdentidade).where(
        CacheIdentidade.tipo == tipo,
        CacheIdentidade.chave == chave,
        CacheIdentidade.expira_em > agora,
    ))
    if not entrada:
        return None
    try:
        payload = json.loads(entrada.payload)
    except (TypeError, ValueError):
        return None
    return {
        "payload": payload,
        "fonte": entrada.fonte,
        "url": entrada.url,
        "lido_em": entrada.lido_em,
    }


async def gravar_cache(
    db, tipo: str, chave: str, fonte: str, url: str | None, payload: object,
    validade: timedelta, agora: datetime | None = None,
) -> None:
    agora = agora or datetime.utcnow()
    entrada = await db.scalar(select(CacheIdentidade).where(
        CacheIdentidade.tipo == tipo, CacheIdentidade.chave == chave,
    ))
    if entrada is None:
        entrada = CacheIdentidade(tipo=tipo, chave=chave, fonte=fonte)
        db.add(entrada)
    entrada.fonte = fonte
    entrada.url = url
    entrada.payload = json.dumps(payload, ensure_ascii=False, default=str)
    entrada.lido_em = agora
    entrada.expira_em = agora + validade
    await db.commit()

