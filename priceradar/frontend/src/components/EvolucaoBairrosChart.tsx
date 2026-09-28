import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { buscarEvolucaoBairros } from '../api/client'
import type { EvolucaoBairrosResponse, PontoEvolucaoBairro } from '../types'
import {
  descricaoSemana,
  formatarEixoMoeda,
  formatarMoeda,
  pluralAnuncios,
  rotuloSemana,
} from '../utils/evolucao'

interface Props {
  cidade: string
  quartos?: number | null
  /** Bairros da busca atual. Vazio/ausente → o backend devolve os de maior volume. */
  bairros?: string[] | null
}

/** Mais que isso vira novelo — e é também o número de cores da paleta. */
const MAX_LINHAS = 6

/**
 * Paleta categórica validada (scripts do dataviz) contra a superfície
 * `mrv-surface` (#0D1F17): todas com contraste >= 3:1 e separáveis por
 * daltônicos entre vizinhas. Fica de fora o verde escuro da marca, que some
 * no fundo verde do app, e o laranja MRV puro, reservado à linha "Ref. MRV".
 */
const CORES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']

// Mesmos valores dos tokens mrv-* (tailwind.config.ts): o Recharts recebe cor
// como string SVG, não classe do Tailwind.
const COR_GRADE = '#1A3D2C'
const COR_EIXO = '#6B9E88'
const COR_SUPERFICIE = '#0D1F17'

function normalizar(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()
}

type Linha = Record<string, string | number | boolean | null>

interface PropsTooltip {
  active?: boolean
  payload?: { payload: Linha }[]
  series: { bairro: string; cor: string }[]
}

function TooltipBairros({ active, payload, series }: PropsTooltip) {
  if (!active || !payload?.length) return null
  const linha = payload[0].payload
  return (
    <div className="rounded-panel border border-mrv-border bg-mrv-surface-2 px-3 py-2 text-[11px] text-mrv-text shadow-card">
      <div className="mb-1.5 text-mrv-text-muted">{String(linha.semana_descricao)}</div>
      {series.map((s, i) => {
        const valor = linha[`t${i}`]
        if (typeof valor !== 'number') return null
        const fraco = linha[`fraco${i}`] === true
        const total = Number(linha[`n${i}`])
        return (
          <div key={s.bairro} className="border-t border-mrv-border/60 py-1.5 first:border-0 first:pt-0">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.cor }} />
              <span className="min-w-0 flex-1 truncate font-medium">{s.bairro}</span>
              <span className="font-data">{formatarMoeda(valor)}/m²</span>
            </div>
            <div className={`pl-4 text-[10px] ${fraco ? 'text-amber-300/90' : 'text-mrv-text-muted'}`}>
              {pluralAnuncios(total)} usado{total === 1 ? '' : 's'} neste ponto
              {fraco ? ' · poucos anúncios, o valor pode oscilar mais' : ''}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Evolução do preço/m² por bairro, semana a semana, a partir do histórico de
 * buscas gravado.
 *
 * Ponto com poucos anúncios (n < min_amostra) não é desenhado como dado firme:
 * fica só na linha tracejada, com marcador vazado. Sem isso, um único anúncio
 * caro numa semana parece "o bairro subiu 20%".
 */
export function EvolucaoBairrosChart({ cidade, quartos, bairros }: Props) {
  const chaveProps = (bairros ?? []).join('|')
  // null = deixar o backend escolher (maior volume); lista = escolha explícita.
  const [pedido, setPedido] = useState<string[] | null>(bairros?.length ? bairros : null)
  const [dados, setDados] = useState<EvolucaoBairrosResponse | null>(null)
  const [carregando, setCarregando] = useState(true)

  // Nova busca (cidade/quartos/bairros) volta ao padrão dela.
  useEffect(() => {
    setPedido(bairros?.length ? bairros : null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cidade, quartos, chaveProps])

  const chavePedido = pedido?.join('|') ?? ''
  useEffect(() => {
    let cancelado = false
    setCarregando(true)
    buscarEvolucaoBairros(cidade, quartos ?? undefined, pedido ?? undefined)
      .then(r => { if (!cancelado) setDados(r) })
      .catch(() => { if (!cancelado) setDados(null) })
      .finally(() => { if (!cancelado) setCarregando(false) })
    return () => { cancelado = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cidade, quartos, chavePedido])

  // Cor segue o bairro, não a posição: tirar "Aldeota" do gráfico não pode
  // repintar "Meireles". Cada bairro que entra ocupa a primeira cor livre.
  const slots = useRef(new Map<string, number>())
  useEffect(() => { slots.current = new Map() }, [cidade])

  const series = useMemo(() => {
    const lista = dados?.bairros ?? []
    const chaves = lista.map(b => normalizar(b.bairro))
    const mapa = slots.current
    for (const k of [...mapa.keys()]) if (!chaves.includes(k)) mapa.delete(k)
    const usados = new Set(mapa.values())
    for (const k of chaves) {
      if (mapa.has(k)) continue
      let i = 0
      while (usados.has(i)) i++
      mapa.set(k, i)
      usados.add(i)
    }
    return lista.map((b, i) => ({ ...b, cor: CORES[(mapa.get(chaves[i]) ?? i) % CORES.length] }))
  }, [dados])

  const chartData = useMemo(() => {
    if (!dados) return []
    return dados.periodos.map(semana => {
      const linha: Linha = {
        semana,
        semana_fmt: rotuloSemana(semana),
        semana_descricao: descricaoSemana(semana),
      }
      series.forEach((s, i) => {
        const p: PontoEvolucaoBairro | undefined = s.serie.find(x => x.semana === semana)
        // t = todos os pontos (linha tracejada); f = só os firmes (linha cheia).
        linha[`t${i}`] = p ? p.preco_m2_medio : null
        linha[`f${i}`] = p && !p.pouco_confiavel ? p.preco_m2_medio : null
        linha[`n${i}`] = p ? p.n : null
        linha[`fraco${i}`] = p ? p.pouco_confiavel : false
      })
      return linha
    })
  }, [dados, series])

  if (carregando && !dados) {
    return (
      <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5 animate-pulse">
        <div className="h-2.5 bg-mrv-surface-2/80 rounded w-1/3 mb-6" />
        <div className="h-36 bg-mrv-surface-2/40 rounded-card" />
      </div>
    )
  }
  if (!dados) return null

  const selecionados = new Set(series.map(s => normalizar(s.bairro)))
  // Chips = legenda + seletor. Inclui bairro pedido que ainda não tem histórico.
  const opcoes = [
    ...dados.disponiveis,
    ...series.filter(s => s.total === 0).map(s => ({ bairro: s.bairro, total: 0 })),
  ]

  function alternar(bairro: string) {
    const k = normalizar(bairro)
    const atuais = series.map(s => s.bairro)
    const novo = selecionados.has(k)
      ? atuais.filter(b => normalizar(b) !== k)
      : [...atuais, bairro].slice(0, MAX_LINHAS)
    // Nunca zera: sem nenhum bairro o gráfico não teria o que mostrar.
    if (novo.length) setPedido(novo)
  }

  const titulo = (
    <div className="mb-4">
      <h2 className="text-sm font-semibold text-mrv-text">
        Preço por m² ao longo do tempo — bairros de {cidade}
        {quartos ? ` · ${quartos} quartos` : ''}
      </h2>
      <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-mrv-text-muted">
        Compare os bairros semana a semana. Linha subindo significa anúncios mais caros por m²;
        linha descendo, anúncios mais baratos.
      </p>
    </div>
  )

  if (dados.periodos.length < 2) {
    return (
      <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5">
        {titulo}
        <p className="text-xs text-mrv-text-muted leading-relaxed">
          {dados.periodos.length === 0
            ? 'Ainda não há histórico de bairros para esta cidade.'
            : 'Por enquanto só há uma semana de histórico.'}{' '}
          A série cresce a cada busca: com buscas em pelo menos duas semanas diferentes, a
          evolução do preço/m² de cada bairro aparece aqui.
        </p>
      </div>
    )
  }

  const semHistorico = series.filter(s => s.total === 0).map(s => s.bairro)

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5">
      {titulo}

      <div className="flex flex-wrap gap-1.5 mb-4" role="group" aria-label="Bairros exibidos">
        {opcoes.map(o => {
          const serie = series.find(s => normalizar(s.bairro) === normalizar(o.bairro))
          const ativo = !!serie
          const bloqueado = !ativo && series.length >= MAX_LINHAS
          return (
            <button
              key={o.bairro}
              type="button"
              onClick={() => alternar(o.bairro)}
              disabled={bloqueado}
              aria-pressed={ativo}
              title={bloqueado ? `No máximo ${MAX_LINHAS} bairros por vez` : `${pluralAnuncios(o.total)} diferentes em todas as semanas — cada ponto do gráfico usa só os da semana`}
              className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 text-[11px] transition-colors ${
                ativo
                  ? 'border-mrv-border-bright bg-mrv-surface-2 text-mrv-text'
                  : 'border-mrv-border text-mrv-text-dim hover:text-mrv-text-muted disabled:opacity-40 disabled:cursor-not-allowed'
              }`}
            >
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: serie ? serie.cor : 'transparent', border: serie ? 'none' : `1px solid ${COR_EIXO}` }}
              />
              {o.bairro}
              {/* Total do histórico, não do ponto: o tooltip mostra o da semana. */}
              <span className="text-mrv-text-dim">· {o.total} no histórico</span>
            </button>
          )
        })}
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={COR_GRADE} />
          <XAxis
            dataKey="semana_fmt"
            tick={{ fontSize: 9, fill: COR_EIXO }}
            axisLine={{ stroke: COR_GRADE }}
            tickLine={false}
          />
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={formatarEixoMoeda}
            tick={{ fontSize: 9, fill: COR_EIXO }}
            width={78}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            content={<TooltipBairros series={series} />}
            cursor={{ stroke: COR_EIXO, strokeDasharray: '3 3' }}
          />
          {series.map((s, i) => [
            // Tracejada: o caminho completo, inclusive semanas de amostra fraca
            // (marcador vazado) e buracos de semana sem anúncio.
            <Line
              key={`t${i}`}
              type="linear"
              dataKey={`t${i}`}
              stroke={s.cor}
              strokeOpacity={0.5}
              strokeWidth={1.5}
              strokeDasharray="4 4"
              connectNulls
              isAnimationActive={false}
              activeDot={false}
              legendType="none"
              dot={(props: { cx?: number; cy?: number; index?: number; payload?: Linha }) => {
                const fraco = props.payload?.[`fraco${i}`] === true
                if (!fraco || props.cx == null || props.cy == null) return <g key={`d${i}-${props.index}`} />
                return (
                  <circle
                    key={`d${i}-${props.index}`}
                    cx={props.cx} cy={props.cy} r={4}
                    fill={COR_SUPERFICIE} stroke={s.cor} strokeWidth={1.5}
                  />
                )
              }}
            />,
            // Cheia: só entre pontos firmes (n >= min_amostra).
            <Line
              key={`f${i}`}
              type="linear"
              dataKey={`f${i}`}
              name={s.bairro}
              stroke={s.cor}
              strokeWidth={2}
              connectNulls={false}
              isAnimationActive={false}
              dot={{ r: 4, fill: s.cor, stroke: COR_SUPERFICIE, strokeWidth: 2 }}
              activeDot={{ r: 6, fill: s.cor, stroke: COR_SUPERFICIE, strokeWidth: 2 }}
            />,
          ])}
        </LineChart>
      </ResponsiveContainer>

      <p className="mt-2 max-w-4xl text-[10px] text-mrv-text-dim leading-relaxed">
        Cada ponto usa o preço médio por m² dos anúncios encontrados naquela semana. Marcador vazado:
        menos de {dados.min_amostra} anúncios, o valor pode mudar bastante com a entrada de novos
        imóveis. A linha tracejada passa por esses pontos e também liga semanas em que o bairro
        não teve anúncio; a linha cheia só liga semanas com amostra suficiente.
        {semHistorico.length > 0 && ` Ainda sem dados: ${semHistorico.join(', ')}.`}
      </p>
    </div>
  )
}
