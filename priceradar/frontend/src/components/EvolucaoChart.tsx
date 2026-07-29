import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
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
  return `S${m[2]}/${m[1].slice(2)}`
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
  }))

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5">
      <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] mb-5">
        Evolução Preço/m² — {cidade}
        {quartos ? ` · ${quartos} qtos` : ''}
      </h2>
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
            formatter={(value: number) => [formatarMoeda(value), 'Preço/m² médio']}
            labelFormatter={(label) => `Semana: ${label}`}
            contentStyle={{
              background: '#112D22',
              border: '1px solid #1A4A35',
              borderRadius: '8px',
              fontSize: '11px',
              color: '#E8F0EC',
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, color: '#7BA898' }}
          />
          {precoMrv && (
            <ReferenceLine
              y={precoMrv}
              stroke="#F39200"
              strokeDasharray="6 3"
              strokeWidth={1.5}
              label={{ value: 'Ref. MRV', position: 'insideTopRight', fontSize: 9, fill: '#F39200' }}
            />
          )}
          <Line
            type="monotone"
            dataKey="preco_m2_medio"
            name="Mercado"
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
