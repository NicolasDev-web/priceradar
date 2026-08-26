"""Autenticação simples por senha compartilhada.

Não há tabela de usuários — os dois colegas usam a mesma SENHA_APP. O "token"
é um payload JSON assinado com HMAC-SHA256 (chave = SECRET_KEY), não um JWT
completo: não precisamos de algoritmos plugáveis nem de claims padronizadas,
e um HMAC caseiro cobre 100% do que este app precisa (autenticidade +
expiração) usando só stdlib.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header, HTTPException

SECRET_KEY = os.getenv("SECRET_KEY", "")
SENHA_APP = os.getenv("SENHA_APP", "")
VALIDADE_TOKEN_SEGUNDOS = 30 * 24 * 60 * 60  # 30 dias — sem refresh; expirou, loga de novo.


def _assinar(dados: bytes) -> str:
    if not SECRET_KEY:
        # Falhar alto e cedo: rodar com SECRET_KEY vazia assinaria tokens com
        # chave previsível — pior que não ter login nenhum.
        raise RuntimeError("SECRET_KEY não configurada no .env")
    return hmac.new(SECRET_KEY.encode(), dados, hashlib.sha256).hexdigest()


def conferir_senha(senha: str) -> bool:
    # Comparação em tempo constante: um `==` normal vaza, pelo tempo de
    # resposta, quantos caracteres iniciais bateram.
    if not SENHA_APP:
        return False
    return hmac.compare_digest(senha.encode(), SENHA_APP.encode())


def gerar_token() -> str:
    payload = json.dumps({"exp": int(time.time()) + VALIDADE_TOKEN_SEGUNDOS}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    return f"{payload_b64}.{_assinar(payload_b64.encode())}"


def _token_valido(token: str) -> bool:
    try:
        payload_b64, assinatura = token.split(".", 1)
        if not hmac.compare_digest(assinatura, _assinar(payload_b64.encode())):
            return False
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        return float(payload.get("exp", 0)) > time.time()
    except Exception:
        # Token adulterado/malformado é só mais um "inválido" — não vira 500.
        return False


async def exigir_login(authorization: str | None = Header(default=None)) -> None:
    """Dependency aplicada via `router_protegido` a todas as rotas /api/*
    exceto /api/login e /api/health."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Não autenticado")
    if not _token_valido(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=401, detail="Sessão expirada ou inválida")
