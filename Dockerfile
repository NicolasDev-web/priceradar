# PriceRadar — imagem única: FastAPI serve a API e a SPA compilada.
#
# Fica na raiz do repositório, e não em `priceradar/backend/`, porque o build
# precisa dos dois lados: o estágio Node compila `frontend/`, o estágio Python
# copia o `dist/` resultante. Um contexto só, um `docker build .`.

# ── Estágio 1: compilar a SPA ────────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /frontend
COPY priceradar/frontend/package*.json ./
RUN npm ci
COPY priceradar/frontend/ ./
# `npm run build` roda `tsc` antes do Vite: erro de tipo quebra o build aqui,
# que é onde se quer descobrir, e não em produção.
RUN npm run build


# ── Estágio 2: runtime ───────────────────────────────────────────────────────
# 3.13 é a versão do venv de desenvolvimento (`pyvenv.cfg`).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/priceradar/backend

COPY priceradar/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium é o nível 3 da coleta e dispara sempre que o direto e a ScraperAPI
# falham — sem chave configurada, o nível 2 nunca passa, então o fallback é
# real, não decorativo. Instalar pelo próprio playwright (em vez de usar a
# imagem `mcr.microsoft.com/playwright`) garante que o browser case com a versão
# que o pip resolveu; tag errada = Chromium ausente só na hora do fallback.
# `--with-deps` traz as bibliotecas de sistema via apt. Pesa ~400 MB.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY priceradar/backend/ ./
COPY --from=frontend /frontend/dist /app/priceradar/frontend/dist

# Tudo que sobrevive a um restart mora aqui. O filesystem do container é
# efêmero: sem montar um volume em /data, some o histórico, o cache de buscas
# e o referencial MRV — que é digitado à mão e não se regenera sozinho.
ENV DATABASE_URL="sqlite+aiosqlite:////data/priceradar.db" \
    BAIRROS_CACHE_PATH=/data/bairros_por_cidade.json \
    HISTORICO_FONTES_PATH=/data/historico_fontes.json \
    BROWSER_PROFILE_DIR=/data/browser_profile
VOLUME /data

EXPOSE 8002

# `--proxy-headers` faz o uvicorn confiar no X-Forwarded-* de quem termina o
# TLS na frente (Caddy), senão as URLs que ele gera saem em http.
# Um worker só: o cache de bairros e o histórico de fontes são coordenados por
# lock de processo (`threading.Lock`), que não atravessa workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--proxy-headers", "--workers", "1"]
