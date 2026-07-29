from datetime import datetime

from pydantic import BaseModel, field_validator


class Empreendimento(BaseModel):
    id: str
    nome_anuncio: str
    nome_empreendimento: str | None
    construtora: str | None
    cidade: str
    bairro: str | None
    # Logradouro. Vem separado do bairro porque o JSON-LD dos portais traz os
    # dois em campos distintos e misturá-los quebrava o filtro de bairro.
    endereco: str | None = None
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


_UFS = {
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms",
    "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc",
    "sp", "se", "to",
}


class BuscaRequest(BaseModel):
    cidade: str
    preco_min: float
    preco_max: float
    quartos: int | None = None
    bairro: str | None = None

    @field_validator("cidade")
    @classmethod
    def exigir_estado(cls, v: str) -> str:
        """
        A cidade precisa vir como "Cidade, UF".

        Sem o estado o código assumia SP silenciosamente: buscar "Fortaleza"
        devolvia dados de Fortaleza/SP. Numa ferramenta de precificação, dado
        da praça errada apresentado como certo é pior que erro na cara.
        """
        partes = [p.strip() for p in v.split(",")]
        if len(partes) < 2 or not partes[0]:
            raise ValueError(
                'Informe a cidade com o estado, no formato "Cidade, UF". Ex: "Fortaleza, CE"'
            )
        uf = partes[1].lower()
        if uf not in _UFS:
            raise ValueError(f'"{partes[1]}" não é uma UF válida. Use a sigla de 2 letras, ex: "Fortaleza, CE"')
        return v


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
