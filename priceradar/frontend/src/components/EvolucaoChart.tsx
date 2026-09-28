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
import {
  descricaoSemana,
  formatarEixoMoeda,
  formatarMoeda,
  pluralAnuncios,
  rotuloSemana,
} from '../utils/evolucao'

// Mesmos valores do EvolucaoBairrosChart (tokens mrv-*).
const COR_SUPERFICIE = '#0D1F17'
const COR_LINHA = '#0B5A42'
const COR_PONTO = '#0D6B4F'

interface Props {
  cidade: string
  quartos?: number | null
}

type PontoGrafico = PontoEvolucao & {
  semana_fmt: string
  semana_descricao: string
  /** Todos os pontos (linha tracejada) e só os firmes (linha cheia). */
  todos: number
  firme: number | null
}

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
      <div className={`mt-0.5 text-[10px] ${ponto.pouco_confiavel ? 'text-amber-300/90' : 'text-mrv-text-muted'}`}>
        Média calculada com {pluralAnuncios(ponto.total)} encontrados nessa semana
        {ponto.pouco_confiavel ? ' · poucos anúncios, o valor pode oscilar mais' : ''}
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

  const chartData: PontoGrafico[] = serie.map(p => ({
    ...p,
    semana_fmt: rotuloSemana(p.semana),
    semana_descricao: descricaoSemana(p.semana),
    todos: p.preco_m2_medio,
    firme: p.pouco_confiavel ? null : p.preco_m2_medio,
  }))
  const temSemanaFraca = serie.some(p => p.pouco_confiavel)

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
            domain={['auto', 'auto']}
            tickFormatter={formatarEixoMoeda}
            tick={{ fontSize: 9, fill: '#4A7A65' }}
            width={78}
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
              // Com o eixo em 'auto', a referência fora da faixa dos anúncios
              // sumiria; estender o domínio mantém a comparação visível.
              ifOverflow="extendDomain"
              label={{ value: 'Referência MRV', position: 'insideTopRight', fontSize: 9, fill: '#F39200' }}
            />
          )}
          {/* Tracejada: o caminho inteiro, com marcador vazado nas semanas de
              poucos anúncios. Cheia: só entre semanas com amostra firme. */}
          <Line
            type="linear"
            dataKey="todos"
            stroke={COR_LINHA}
            strokeOpacity={0.6}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            isAnimationActive={false}
            activeDot={false}
            dot={(props: { cx?: number; cy?: number; index?: number; payload?: PontoGrafico }) => {
              if (!props.payload?.pouco_confiavel || props.cx == null || props.cy == null) {
                return <g key={`d${props.index}`} />
              }
              return (
                <circle
                  key={`d${props.index}`}
                  cx={props.cx} cy={props.cy} r={4}
                  fill={COR_SUPERFICIE} stroke={COR_PONTO} strokeWidth={1.5}
                />
              )
            }}
          />
          <Line
            type="linear"
            dataKey="firme"
            name="Todos os anúncios da cidade"
            stroke={COR_LINHA}
            strokeWidth={2}
            connectNulls={false}
            isAnimationActive={false}
            dot={{ fill: COR_PONTO, r: 3, strokeWidth: 0 }}
            activeDot={{ r: 5, fill: '#F39200' }}
          />
        </LineChart>
      </ResponsiveContainer>
      {temSemanaFraca && (
        <p className="mt-2 max-w-4xl text-[10px] text-mrv-text-dim leading-relaxed">
          Trecho tracejado com marcador vazado: semana com menos de 3 anúncios, em que o valor pode
          mudar bastante com a entrada de novos imóveis.
        </p>
      )}
    </div>
  )
}
