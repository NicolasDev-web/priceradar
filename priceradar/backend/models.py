from datetime import datetime

from pydantic import BaseModel


class Empreendimento(BaseModel):
    id: str
    nome_anuncio: str
    nome_empreendimento: str | None
    construtora: str | None
    cidade: str
    bairro: str | None
    portal: str
    preco: float
    area_m2: float
    preco_m2: float
    # Campos Fase 2 — valor padrão None para compatibilidade com Fase 1
    preco_m2_mrv: float | None = None
    variacao_mrv_pct: float | None = None
    quartos: int | None
    banheiros: int | None
    vagas: int | None
    descricao: str | None
    url_anuncio: str
    data_coleta: datetime
    rf_score: float | None = None


class BuscaRequest(BaseModel):
    cidade: str
    preco_min: float
    preco_max: float
    quartos: int | None = None
    bairro: str | None = None


class BuscaResponse(BaseModel):
    total: int
    preco_m2_medio: float
    preco_m2_min: float
    preco_m2_max: float
    preco_m2_mrv: float | None = None
    empreendimentos: list[Empreendimento]
    tempo_coleta_segundos: float
    do_cache: bool = False


class ExportRequest(BaseModel):
    """Exporta os empreendimentos já buscados, sem refazer o scraping."""
    cidade: str
    preco_m2_medio: float
    empreendimentos: list[Empreendimento]
