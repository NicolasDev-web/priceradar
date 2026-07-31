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
    # torre | provavel_bloco | indefinido. Ver classificar_edificacao() em
    # scraper/parser.py — 'indefinido' é ausência de dado, não de elevador.
    tipo_edificacao: str | None = None
    portal: str
    # Coordenada para o mapa. VivaReal e Zap publicam a do anúncio; os demais
    # portais não publicam nenhuma e são posicionados no centro do bairro.
    # `origem_coordenada`: exata | aproximada_portal | centroide_bairro — o mapa
    # precisa distinguir, senão apresenta palpite como endereço.
    latitude: float | None = None
    longitude: float | None = None
    origem_coordenada: str | None = None
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


class ResumoBairro(BaseModel):
    """
    Recorte de um bairro na busca.

    Existe porque uma mediana única sobre vários bairros esconde exatamente a
    diferença que a análise procura — Aldeota e Messejana no mesmo número não
    respondem "onde compensa lançar?".
    """
    bairro: str
    total: int
    preco_m2_mediana: float
    preco_m2_medio: float
    preco_m2_min: float
    preco_m2_max: float


class DiagnosticoColeta(BaseModel):
    """Saúde da coleta. Permite distinguir 'não há imóveis' de 'a coleta falhou'."""
    total_bruto: int = 0
    # Quantos anúncios vieram com coordenada do portal. O formato de onde ela
    # sai não é documentado: se cair a zero de um dia para o outro, foi o portal
    # que mudou — e isso precisa aparecer, não virar um mapa vazio sem motivo.
    com_coordenada: int = 0
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
    # `bairro` continua aceito para não quebrar o histórico e o cache já
    # gravados; `bairros` é a forma nova. Use sempre `lista_bairros`.
    bairro: str | None = None
    bairros: list[str] | None = None
    # torre | provavel_bloco | indefinido. Nenhum portal filtra elevador na
    # origem, então é aplicado depois da coleta.
    tipo_edificacao: str | None = None

    @property
    def lista_bairros(self) -> list[str]:
        """Bairros pedidos, sem duplicata e sem vazio, vindos de qualquer campo."""
        brutos = list(self.bairros or [])
        if self.bairro:
            brutos.append(self.bairro)
        vistos, saida = set(), []
        for b in brutos:
            limpo = b.strip()
            chave = limpo.lower()
            if limpo and chave not in vistos:
                vistos.add(chave)
                saida.append(limpo)
        return saida

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
    # Preenchido só quando a busca pediu mais de um bairro.
    por_bairro: list[ResumoBairro] = []
    # Anúncios que não puderam ser posicionados no mapa. Sem esse número, um
    # mapa com menos pinos que a lista parece defeito.
    sem_localizacao: int = 0


class ExportRequest(BaseModel):
    """Exporta os empreendimentos já buscados, sem refazer o scraping."""
    cidade: str
    preco_m2_medio: float
    empreendimentos: list[Empreendimento]
