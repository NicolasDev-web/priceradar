import axios from 'axios'
import type {
  BuscaRequest,
  BuscaResponse,
  EvolucaoResponse,
  HistoricoResponse,
  ProgressoBusca,
  ReferencialMRVInput,
  ReferencialMRVResponse,
} from '../types'

// Vazio = mesma origem. Em produção o FastAPI serve o frontend compilado, então
// a API está no mesmo host:porta — e é isso que faz a aplicação funcionar quando
// outra pessoa acessa pela rede: com URL absoluta, "localhost" seria a máquina
// DELA. VITE_API_URL só é usada no desenvolvimento (Vite em 5173, API em 8002).
const BASE_URL = import.meta.env.VITE_API_URL ?? ''

// timeout de 90s: o scraping via ScraperAPI pode levar alguns segundos por portal
const api = axios.create({ baseURL: BASE_URL, timeout: 90_000 })

const TOKEN_KEY = 'priceradar_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

function limparToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export async function login(senha: string): Promise<void> {
  const { data } = await api.post<{ token: string }>('/api/login', { senha })
  setToken(data.token)
}

// Anexa o token em toda chamada — nenhuma das funções abaixo (buscarConcorrentes,
// exportarExcel etc.) precisa saber que autenticação existe.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 = token ausente/expirado/inválido. Limpa e avisa a UI — sem refresh
// (não existe) e sem re-tentar a mesma chamada sozinho.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      limparToken()
      window.dispatchEvent(new Event('priceradar:sessao-expirada'))
    }
    return Promise.reject(error)
  },
)

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

export async function exportarExcel(cidade: string, resultado: BuscaResponse): Promise<void> {
  // Envia os resultados já buscados — não refaz o scraping (instantâneo).
  const response = await api.post(
    '/api/exportar',
    {
      cidade,
      preco_m2_medio: resultado.preco_m2_medio,
      empreendimentos: resultado.empreendimentos,
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
