/**
 * Como a coordenada foi obtida. União fechada de propósito: se o backend
 * passar a mandar um valor novo, o `tsc` do build acusa em vez de o mapa
 * desenhar um pino sem legenda.
 */
export type OrigemCoordenada = 'exata' | 'aproximada_portal' | 'centroide_bairro'

export interface Empreendimento {
  id: string
  nome_anuncio: string
  nome_empreendimento: string | null
  construtora: string | null
  cidade: string
  bairro: string | null
  endereco: string | null
  tipo_edificacao: string | null
  latitude: number | null
  longitude: number | null
  origem_coordenada: OrigemCoordenada | null
  portal: string
  preco: number
  area_m2: number
  preco_m2: number
  preco_m2_mrv: number | null
  variacao_mrv_pct: number | null
  quartos: number | null
  banheiros: number | null
  vagas: number | null
  descricao: string | null
  url_anuncio: string
  data_coleta: string
  rf_score?: number
  campos_imputados?: string[]
  portais_duplicados?: string[]
  /** URLs das fotos da página de resultados, capa primeiro. Vazia = sem foto. */
  fotos?: string[]
  /** Comparação com a última busca igual (ausente na primeira vez). */
  novo?: boolean
  preco_anterior?: number | null
  data_preco_anterior?: string | null
}

export interface ComparacaoBusca {
  data_anterior: string
  novos: number
  baixaram: number
  subiram: number
  sairam: number
}

export interface DiagnosticoColeta {
  total_bruto: number
  com_coordenada: number
  /** Anúncios com ao menos uma foto. Portal com muitos sem foto = extração quebrou. */
  com_foto?: number
  sem_foto_por_portal?: Record<string, number>
  fontes_ok: string[]
  fontes_zero: string[]
  fontes_erro: string[]
  descartados_por_motivo: Record<string, number>
}

export interface BuscaRequest {
  cidade: string
  preco_min: number
  preco_max: number
  quartos: number | null
  /** 1–3 exatos; 4 = 4 ou mais. */
  banheiros?: number | null
  bairro?: string | null
  bairros?: string[] | null
  tipo_edificacao?: string | null
}

export interface ResumoBairro {
  bairro: string
  total: number
  preco_m2_mediana: number
  preco_m2_medio: number
  preco_m2_min: number
  preco_m2_max: number
}

export interface BuscaResponse {
  total: number
  preco_m2_medio: number
  preco_m2_mediana: number
  preco_m2_min: number
  preco_m2_max: number
  preco_m2_mrv: number | null
  empreendimentos: Empreendimento[]
  tempo_coleta_segundos: number
  do_cache: boolean
  diagnostico?: DiagnosticoColeta | null
  por_bairro?: ResumoBairro[]
  sem_localizacao?: number
  comparacao?: ComparacaoBusca | null
}

export interface BuscaSalva {
  id: string
  cidade: string
  preco_min: number
  preco_max: number
  quartos: number | null
  total_encontrado: number
  preco_m2_medio: number
  criado_em: string
}

export interface PontoEvolucao {
  semana: string
  preco_m2_medio: number
  total: number
}

export interface HistoricoResponse {
  buscas: BuscaSalva[]
}

export interface EvolucaoResponse {
  cidade: string
  serie: PontoEvolucao[]
}

export interface ReferencialMRVInput {
  cidade: string
  produto: string
  preco_m2: number
  quartos: number | null
}

export interface ReferencialMRVResponse {
  cidade: string
  quartos: number | null
  preco_m2_mrv: number | null
}

export interface StatusPortal {
  concluidas: number
  esperadas: number
  itens: number
  erro: boolean
}

export interface ProgressoBusca {
  concluido: boolean
  portais: Record<string, StatusPortal>
}
