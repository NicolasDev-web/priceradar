import { useEffect, useState } from 'react'
import { consultarProgressoBusca } from '../api/client'
import type { ProgressoBusca } from '../types'

const INTERVALO_POLL_MS = 1500

/**
 * Progresso por portal de uma busca ao vivo, via polling em
 * `/api/buscar/jobs/{jobId}`. `jobId` nulo (sem busca em andamento, ou busca
 * servida do cache) simplesmente não inicia o polling.
 */
export function useBuscaProgress(jobId: string | null): ProgressoBusca | null {
  const [progresso, setProgresso] = useState<ProgressoBusca | null>(null)

  useEffect(() => {
    setProgresso(null)
    if (!jobId) return

    let cancelado = false
    async function tick() {
      const p = await consultarProgressoBusca(jobId as string)
      if (!cancelado && p) setProgresso(p)
    }

    tick()
    const id = setInterval(tick, INTERVALO_POLL_MS)
    return () => {
      cancelado = true
      clearInterval(id)
    }
  }, [jobId])

  return progresso
}
