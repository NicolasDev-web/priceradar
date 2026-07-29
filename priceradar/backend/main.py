import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

# Playwright requer ProactorEventLoop no Windows para criar subprocessos.
# Deve ser definido antes de uvicorn criar o event loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Validade do cache de buscas: dentro desse tempo, uma busca idêntica reaproveita
# os resultados do banco em vez de refazer o scraping.
CACHE_MINUTOS = int(os.getenv("CACHE_MINUTOS", "60"))

from database.connection import get_db, init_db
from models import BuscaRequest, BuscaResponse, ExportRequest
from repositories.busca_repo import (
    buscar_cache_recente,
    buscar_por_id,
    deletar_busca,
    listar_buscas,
    salvar_busca,
)
from repositories.empreendimento_repo import (
    get_referencial_mrv,
    preco_m2_historico,
    upsert_referencial_mrv,
)
from services.export import gerar_excel
from services.search import executar_busca


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Banco de dados inicializado")
    yield


app = FastAPI(title="PriceRadar API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "timestamp": datetime.now().isoformat()}


@app.post("/api/buscar", response_model=BuscaResponse)
async def buscar(
    request: BuscaRequest,
    forcar: bool = Query(default=False, description="Ignora o cache e refaz o scraping"),
    db: AsyncSession = Depends(get_db),
):
    try:
        logger.info(f"Busca: {request.cidade} R${request.preco_min}–{request.preco_max} q={request.quartos} forcar={forcar}")
        preco_m2_mrv = await get_referencial_mrv(db, request.cidade, request.quartos)

        # Cache: reaproveita uma busca idêntica recente, a menos que forcar=true
        if not forcar:
            cache = await buscar_cache_recente(db, request, CACHE_MINUTOS, preco_m2_mrv)
            if cache is not None:
                logger.info(f"Cache HIT: {cache.total} resultados reaproveitados")
                cache.do_cache = True
                return cache

        resultado = await executar_busca(request, preco_m2_mrv)
        await salvar_busca(db, request, resultado)
        return resultado
    except Exception as e:
        logger.error(f"Erro em /api/buscar: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/exportar")
async def exportar(payload: ExportRequest):
    """Gera o Excel a partir dos resultados já buscados (não refaz scraping)."""
    try:
        if not payload.empreendimentos:
            raise HTTPException(status_code=400, detail="Nenhum resultado para exportação")
        xlsx = gerar_excel(payload.empreendimentos, payload.preco_m2_medio)
        cidade_slug = payload.cidade.replace(' ', '_').replace(',', '')
        nome = f"priceradar_{cidade_slug}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro em /api/exportar: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Histórico ──────────────────────────────────────────────────────────────────

@app.get("/api/historico")
async def listar_historico(cidade: str | None = None, db: AsyncSession = Depends(get_db)):
    buscas = await listar_buscas(db, cidade=cidade)
    return {
        "buscas": [
            {
                "id": b.id, "cidade": b.cidade, "preco_min": b.preco_min, "preco_max": b.preco_max,
                "quartos": b.quartos, "total_encontrado": b.total_encontrado,
                "preco_m2_medio": b.preco_m2_medio, "criado_em": b.criado_em.isoformat(),
            }
            for b in buscas
        ]
    }


@app.get("/api/historico/evolucao")
async def evolucao_preco(cidade: str, quartos: int | None = None, db: AsyncSession = Depends(get_db)):
    dados = await preco_m2_historico(db, cidade, quartos)
    return {"cidade": cidade, "serie": dados}


@app.get("/api/historico/{busca_id}")
async def detalhe_historico(busca_id: str, db: AsyncSession = Depends(get_db)):
    busca = await buscar_por_id(db, busca_id)
    if not busca:
        raise HTTPException(status_code=404, detail="Busca não encontrada")
    return busca


@app.delete("/api/historico/{busca_id}")
async def deletar_historico(busca_id: str, db: AsyncSession = Depends(get_db)):
    ok = await deletar_busca(db, busca_id)
    return {"ok": ok}


# ── Referencial MRV ────────────────────────────────────────────────────────────

@app.post("/api/mrv/referencial")
async def cadastrar_referencial(
    cidade: str,
    produto: str,
    preco_m2: float,
    quartos: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    await upsert_referencial_mrv(db, cidade, produto, quartos, preco_m2)
    return {"ok": True}


@app.get("/api/mrv/referencial")
async def consultar_referencial(
    cidade: str,
    quartos: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    preco = await get_referencial_mrv(db, cidade, quartos)
    return {"cidade": cidade, "quartos": quartos, "preco_m2_mrv": preco}
