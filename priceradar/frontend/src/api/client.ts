import axios from 'axios'
import type {
  BuscaRequest,
  BuscaResponse,
  EvolucaoBairrosResponse,
  EvolucaoResponse,
  HistoricoResponse,
  ProgressoBusca,
  ReferencialMRVInput,
  ReferencialMRVResponse,
} from '../types'

// Vazio = mesma origem. O mesmo build roda em dois lugares:
// - servido pelo próprio FastAPI (link da rede do escritório, localhost, Funnel):
//   a API está no mesmo host:porta. Usar a URL do Funnel aqui faria o navegador
//   de quem abriu pelo IP da rede cair no CORS e ver só "Network Error";
// - no Cloudflare Pages: a API está em outro host, o de VITE_API_URL.
// No `npm run dev` o Vite está em 5173 e a API em 8002 (.env.development).
const API_EM_OUTRO_HOST = import.meta.env.DEV || window.location.hostname.endsWith('.pages.dev')
const BASE_URL = API_EM_OUTRO_HOST ? (import.meta.env.VITE_API_URL ?? '') : ''

// timeout de 90s: o scraping via ScraperAPI pode levar alguns segundos por portal
const api = axios.create({ baseURL: BASE_URL, timeout: 90_000 })

/**
 * Molde de URL dos tiles do mapa, servidos pelo proxy do backend (a chave da
 * CARTO fica lá, não no bundle).
 */
export function urlTilesMapa(): string {
  return `${BASE_URL}/api/tiles/{z}/{x}/{y}.png?r={r}`
}

/** A mesma foto via backend — plano B quando o CDN do portal não carrega
 *  (rede corporativa, hotlink). */
export function urlImagemProxy(url: string): string {
  return `${BASE_URL}/api/imagem?u=${encodeURIComponent(url)}`
}

// Cache de resposta de busca no sessionStorage — TTL curto, só para proteger
// contra reenvio acidental do mesmo formulário ou "voltar" no navegador. Não
// substitui o cache do backend (que é o que evita reprocessar o scraping).
const CACHE_BUSCA_TTL_MS = 3 * 60 * 1000
const CACHE_BUSCA_PREFIXO = 'priceradar_busca:'

function chaveCacheBusca(params: BuscaRequest, forcar: boolean): string {
  return CACHE_BUSCA_PREFIXO + JSON.stringify({ ...params, forcar })
}

function lerCacheBusca(chave: string): BuscaResponse | null {
  try {
    const bruto = sessionStorage.getItem(chave)
    if (!bruto) return null
    const { ts, dados } = JSON.parse(bruto) as { ts: number; dados: BuscaResponse }
    if (Date.now() - ts > CACHE_BUSCA_TTL_MS) {
      sessionStorage.removeItem(chave)
      return null
    }
    return dados
  } catch {
    return null
  }
}

function salvarCacheBusca(chave: string, dados: BuscaResponse): void {
  try {
    sessionStorage.setItem(chave, JSON.stringify({ ts: Date.now(), dados }))
  } catch {
    // sessionStorage indisponível ou cheio — o cache é só conveniência.
  }
}

export async function buscarConcorrentes(
  params: BuscaRequest,
  forcar = false,
  opts: { jobId?: string; signal?: AbortSignal } = {},
): Promise<BuscaResponse> {
  const chave = chaveCacheBusca(params, forcar)
  if (!forcar) {
    const emCache = lerCacheBusca(chave)
    if (emCache) return emCache
  }
  const { data } = await api.post<BuscaResponse>('/api/buscar', params, {
    params: {
      ...(forcar ? { forcar: true } : {}),
      ...(opts.jobId ? { job_id: opts.jobId } : {}),
    },
    signal: opts.signal,
  })
  salvarCacheBusca(chave, data)
  return data
}

/** Progresso por portal de uma busca ao vivo em andamento (polling). */
export async function consultarProgressoBusca(jobId: string): Promise<ProgressoBusca | null> {
  try {
    const { data } = await api.get<ProgressoBusca>(`/api/buscar/jobs/${jobId}`)
    return data
  } catch {
    // 404 = job ainda não criado no backend, ou já expirou — não é erro.
    return null
  }
}

export async function exportarExcel(busca: BuscaRequest, resultado: BuscaResponse): Promise<void> {
  // Envia os resultados já buscados — não refaz o scraping (instantâneo). Os
  // filtros e o referencial MRV vão junto para o cabeçalho e a aba CONFIG.
  const response = await api.post(
    '/api/exportar',
    {
      cidade: busca.cidade,
      preco_m2_medio: resultado.preco_m2_medio,
      empreendimentos: resultado.empreendimentos,
      preco_m2_mrv: resultado.preco_m2_mrv,
      preco_min: busca.preco_min,
      preco_max: busca.preco_max,
      quartos: busca.quartos,
      banheiros: busca.banheiros ?? null,
      bairros: busca.bairros ?? null,
      tipo_edificacao: busca.tipo_edificacao ?? null,
      fontes: resultado.diagnostico?.fontes_ok ?? null,
    },
    { responseType: 'blob' },
  )
  const url = window.URL.createObjectURL(new Blob([response.data]))
  const link = document.createElement('a')
  link.href = url
  const disposition = response.headers['content-disposition'] ?? ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  link.download = match ? match[1] : 'priceradar.xlsx'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export async function listarHistorico(cidade?: string): Promise<HistoricoResponse> {
  const { data } = await api.get<HistoricoResponse>('/api/historico', {
    params: cidade ? { cidade } : undefined,
  })
  return data
}

export async function deletarHistorico(id: string): Promise<void> {
  await api.delete(`/api/historico/${id}`)
}

export async function buscarEvolucao(cidade: string, quartos?: number): Promise<EvolucaoResponse> {
  const { data } = await api.get<EvolucaoResponse>('/api/historico/evolucao', {
    params: { cidade, quartos },
  })
  return data
}

/**
 * Evolução do preço/m² por bairro. Sem `bairros`, o backend escolhe os de
 * maior volume. Vai como texto separado por vírgula (um dos dois formatos que
 * o endpoint aceita) para não depender de como o axios serializa arrays.
 */
export async function buscarEvolucaoBairros(
  cidade: string,
  quartos?: number,
  bairros?: string[],
): Promise<EvolucaoBairrosResponse> {
  const { data } = await api.get<EvolucaoBairrosResponse>('/api/historico/evolucao-bairros', {
    params: { cidade, quartos, bairros: bairros?.length ? bairros.join(',') : undefined },
  })
  return data
}

export async function cadastrarReferencialMRV(dados: ReferencialMRVInput): Promise<void> {
  await api.post('/api/mrv/referencial', null, {
    params: {
      cidade: dados.cidade,
      produto: dados.produto,
      preco_m2: dados.preco_m2,
      quartos: dados.quartos ?? undefined,
    },
  })
}

export async function consultarReferencialMRV(
  cidade: string,
  quartos?: number,
): Promise<ReferencialMRVResponse> {
  const { data } = await api.get<ReferencialMRVResponse>('/api/mrv/referencial', {
    params: { cidade, quartos },
  })
  return data
}

/** Bairros com oferta na cidade, para sugerir no formulário. */
export async function listarBairros(cidade: string): Promise<string[]> {
  try {
    const { data } = await api.get<{ bairros: string[] }>('/api/bairros', { params: { cidade } })
    return data.bairros ?? []
  } catch {
    // Sugestão é conveniência — falhar aqui não pode travar o formulário.
    return []
  }
}
