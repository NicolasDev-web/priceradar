import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { buscarEvolucao, consultarReferencialMRV } from '../api/client'
import type { PontoEvolucao } from '../types'

interface Props {
  cidade: string
  quartos?: number | null
}

function formatarMoeda(v: number): string {
  return `R$ ${v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function formatarSemana(semana: string): string {
  const m = semana.match(/(\d{4})-W(\d+)/)
  if (!m) return semana
  return `sem. ${m[2]}/${m[1].slice(2)}`
}

function descreverSemana(semana: string): string {
  const m = semana.match(/(\d{4})-W(\d+)/)
  if (!m) return semana
  return `Semana ${Number(m[2])} de ${m[1]}`
}

function pluralAnuncios(total: number): string {
  return `${total} ${total === 1 ? 'anúncio' : 'anúncios'}`
}

type PontoGrafico = PontoEvolucao & { semana_fmt: string; semana_descricao: string }

interface PropsTooltip {
  active?: boolean
  payload?: { payload: PontoGrafico }[]
}

function TooltipCidade({ active, payload }: PropsTooltip) {
  if (!active || !payload?.length) return null
  const ponto = payload[0].payload
  return (
    <div className="rounded-panel border border-mrv-border bg-mrv-surface-2 px-3 py-2 text-[11px] text-mrv-text shadow-card">
      <div className="mb-1 text-mrv-text-muted">{ponto.semana_descricao}</div>
      <div className="font-data font-semibold">{formatarMoeda(ponto.preco_m2_medio)}/m²</div>
      <div className="mt-0.5 text-[10px] text-mrv-text-muted">
        Média calculada com {pluralAnuncios(ponto.total)} encontrados nessa semana
      </div>
    </div>
  )
}

export function EvolucaoChart({ cidade, quartos }: Props) {
  const [serie, setSerie] = useState<PontoEvolucao[]>([])
  const [precoMrv, setPrecoMrv] = useState<number | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    setCarregando(true)
    Promise.all([
      buscarEvolucao(cidade, quartos ?? undefined),
      consultarReferencialMRV(cidade, quartos ?? undefined),
    ])
      .then(([ev, ref]) => {
        setSerie(ev.serie)
        setPrecoMrv(ref.preco_m2_mrv)
      })
      .catch(() => { setSerie([]); setPrecoMrv(null) })
      .finally(() => setCarregando(false))
  }, [cidade, quartos])

  if (carregando) {
    return (
      <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5 animate-pulse">
        <div className="h-2.5 bg-mrv-surface-2/80 rounded w-1/4 mb-6" />
        <div className="h-36 bg-mrv-surface-2/40 rounded-card" />
      </div>
    )
  }

  if (serie.length < 2) return null

  const chartData = serie.map(p => ({
    ...p,
    semana_fmt: formatarSemana(p.semana),
    semana_descricao: descreverSemana(p.semana),
  }))

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5">
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-mrv-text">
          Preço por m² ao longo do tempo — visão geral de {cidade}
          {quartos ? ` · ${quartos} quartos` : ''}
        </h2>
        <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-mrv-text-muted">
          Reúne todos os anúncios encontrados para mostrar se o preço anunciado da cidade está
          subindo, caindo ou permanecendo estável a cada semana.
        </p>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1A4A35" />
          <XAxis
            dataKey="semana_fmt"
            tick={{ fontSize: 9, fill: '#4A7A65' }}
            axisLine={{ stroke: '#1A4A35' }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v) => `R$ ${(v / 1000).toFixed(0)}k`}
            tick={{ fontSize: 9, fill: '#4A7A65' }}
            width={68}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            content={<TooltipCidade />}
          />
          {precoMrv && (
            <ReferenceLine
              y={precoMrv}
              stroke="#F39200"
              strokeDasharray="6 3"
              strokeWidth={1.5}
              label={{ value: 'Referência MRV', position: 'insideTopRight', fontSize: 9, fill: '#F39200' }}
            />
          )}
          <Line
            type="monotone"
            dataKey="preco_m2_medio"
            name="Todos os anúncios da cidade"
            stroke="#0B5A42"
            strokeWidth={2}
            dot={{ fill: '#0D6B4F', r: 3, strokeWidth: 0 }}
            activeDot={{ r: 5, fill: '#F39200' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
