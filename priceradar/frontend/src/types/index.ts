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
  cep?: string | null
  /** true = lançamento declarado; false = pronto declarado; null = o anúncio não diz. */
  eh_lancamento?: boolean | null
  /** Empreendimento (prédio) ao qual o anúncio pertence; null = sem outro anúncio ligado. */
  grupo_id?: string | null
  /** confirmado: conta no preço do grupo; provavel: sem número no ponto do prédio — fora do preço. */
  vinculo_grupo?: 'confirmado' | 'provavel' | null
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
  /** Empreendimentos com 2+ anúncios nesta busca, do maior para o menor. */
  grupos?: GrupoEmpreendimento[]
  /** Mediana em que cada prédio conta uma vez. */
  preco_m2_mediana_por_empreendimento?: number | null
}

/** Regra que uniu os anúncios do grupo. */
export type SinalGrupo = 'endereco' | 'coordenada' | 'nome'

/**
 * Nível de prova do grupo — é a aba onde ele aparece.
 * mesmo_predio: rua e número idênticos. mesmo_local: mesmo ponto do mapa, sem
 * número para confirmar. mesmo_nome: só o nome liga os anúncios.
 */
export type NivelGrupo = 'mesmo_predio' | 'mesmo_local' | 'mesmo_nome'

export interface GrupoEmpreendimento {
  grupo_id: string
  chave: string
  nome: string | null
  endereco: string | null
  bairro: string | null
  cidade: string
  construtora: string | null
  latitude: number | null
  longitude: number | null
  n_anuncios: number
  /** Unidades distintas: a mesma unidade anunciada duas vezes conta uma. */
  n_unidades: number
  preco_m2_mediana: number
  preco_m2_medio: number
  preco_m2_min: number
  preco_m2_max: number
  area_min: number | null
  area_max: number | null
  preco_min: number | null
  preco_max: number | null
  quartos: number[]
  portais: string[]
  eh_lancamento: boolean | null
  /** alta: endereço ou coordenada; media: só o nome. */
  nivel: NivelGrupo
  confianca: 'alta' | 'media' | 'baixa'
  sinais: SinalGrupo[]
  /** URLs dos anúncios prováveis (sem número no ponto do prédio) — fora das estatísticas. */
  anexos: string[]
  n_provaveis: number
  foto: string | null
}

/** Por que um anúncio entrou no dossiê. */
export type MotivoAnuncio =
  | 'endereco' | 'coordenada' | 'mesmo_predio' | 'mesmo_local' | 'anexo' | 'nome' | 'texto' | 'rua'

export interface AnuncioDossie {
  url_anuncio: string
  portal: string
  nome_anuncio: string | null
  nome_empreendimento: string | null
  preco: number
  area_m2: number
  preco_m2: number
  quartos: number | null
  banheiros: number | null
  vagas: number | null
  bairro: string | null
  endereco: string | null
  foto: string | null
  primeira_vez: string | null
  ultima_vez: string | null
  /** Visto na coleta mais recente do mesmo portal no mesmo bairro (janela de 14 dias). */
  ativo: boolean
  variacao_vs_grupo_pct: number | null
  motivo: MotivoAnuncio | null
}

export interface DossieEmpreendimento {
  grupo: GrupoEmpreendimento | null
  anuncios: AnuncioDossie[]
  ativos: number
  provaveis: AnuncioDossie[]
  serie: PontoEvolucaoBairro[]
  min_amostra: number
  aviso: string | null
  /** Só na busca por nome/endereço. */
  alvo?: {
    nome: string | null
    endereco: string | null
    latitude: number | null
    longitude: number | null
    endereco_encontrado: string | null
    geocodificacao_precisa: boolean
  }
  sugestoes?: GrupoEmpreendimento[]
  total_historico?: number
  /** Coleta direcionada: feita, pulada por falta de bairro, ou não pedida. */
  coleta?: 'feita' | 'sem_bairro' | null
}

export interface ProcurarEmpreendimentoRequest {
  cidade: string
  nome?: string | null
  endereco?: string | null
  bairro?: string | null
  raio_m?: number
  coletar?: boolean
}

export interface BuscaSalva {
  id: string
  cidade: string
  preco_min: number
  preco_max: number
  quartos: number | null
  /** Filtros que mudam o resultado — sem eles, reabrir fazia outra busca. */
  bairros?: string[] | null
  banheiros?: number | null
  tipo_edificacao?: string | null
  total_encontrado: number
  preco_m2_medio: number
  criado_em: string
}

export interface PontoEvolucao {
  semana: string
  preco_m2_medio: number
  total: number
  /** Menos anúncios que o mínimo (3): desenhado tracejado, não como tendência. */
  pouco_confiavel: boolean
}

export interface HistoricoResponse {
  buscas: BuscaSalva[]
}

export interface EvolucaoResponse {
  cidade: string
  serie: PontoEvolucao[]
}

/** Um ponto da evolução por bairro: uma semana ('%Y-W%W') de um bairro. */
export interface PontoEvolucaoBairro {
  semana: string
  preco_m2_medio: number
  preco_m2_mediana: number
  /** Anúncios distintos do bairro na semana. */
  n: number
  /** n abaixo de `min_amostra`: desenhar sem destaque, nunca como dado firme. */
  pouco_confiavel: boolean
}

export interface SerieBairro {
  bairro: string
  /** Anúncios distintos no histórico todo (volume). */
  total: number
  serie: PontoEvolucaoBairro[]
}

export interface EvolucaoBairrosResponse {
  cidade: string
  quartos: number | null
  min_amostra: number
  periodos: string[]
  /** Todos os bairros com histórico, por volume — para o seletor. */
  disponiveis: { bairro: string; total: number }[]
  bairros: SerieBairro[]
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
