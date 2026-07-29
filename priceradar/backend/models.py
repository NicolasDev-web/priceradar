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
    # Transparência: campos preenchidos por imputação (não vieram do anúncio)
    # e outros portais onde o mesmo imóvel foi encontrado.
    campos_imputados: list[str] = []
    portais_duplicados: list[str] = []


class DiagnosticoColeta(BaseModel):
    """Saúde da coleta. Permite distinguir 'não há imóveis' de 'a coleta falhou'."""
    total_bruto: int = 0
    fontes_ok: list[str] = []
    fontes_zero: list[str] = []
    fontes_erro: list[str] = []
    descartados_por_motivo: dict[str, int] = {}


class BuscaRequest(BaseModel):
    cidade: str
    preco_min: float
    preco_max: float
    quartos: int | None = None
    bairro: str | None = None


class BuscaResponse(BaseModel):
    total: int
    preco_m2_medio: float
    # Mediana é o número de referência: não se move com outlier, ao contrário
    # da média. É o valor que deve ser levado para a reunião comercial.
    preco_m2_mediana: float = 0.0
    preco_m2_min: float
    preco_m2_max: float
    preco_m2_mrv: float | None = None
    empreendimentos: list[Empreendimento]
    tempo_coleta_segundos: float
    do_cache: bool = False
    diagnostico: DiagnosticoColeta | None = None


class ExportRequest(BaseModel):
    """Exporta os empreendimentos já buscados, sem refazer o scraping."""
    cidade: str
    preco_m2_medio: float
    empreendimentos: list[Empreendimento]
