import axios from 'axios'
import type {
  BuscaRequest,
  BuscaResponse,
  EvolucaoResponse,
  HistoricoResponse,
  ReferencialMRVInput,
  ReferencialMRVResponse,
} from '../types'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// timeout de 90s: o scraping via ScraperAPI pode levar alguns segundos por portal
const api = axios.create({ baseURL: BASE_URL, timeout: 90_000 })

export async function buscarConcorrentes(
  params: BuscaRequest,
  forcar = false,
): Promise<BuscaResponse> {
  const { data } = await api.post<BuscaResponse>('/api/buscar', params, {
    params: forcar ? { forcar: true } : undefined,
  })
  return data
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
