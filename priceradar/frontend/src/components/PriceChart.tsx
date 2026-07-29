import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { BuscaResponse, Empreendimento } from '../types'

interface Props {
  dados: BuscaResponse
}

function corBarra(preco_m2: number, media: number): string {
  if (preco_m2 < media * 0.92) return '#22C55E'  // verde vivo — abaixo da média
  if (preco_m2 > media * 1.08) return '#EF4444'  // vermelho — acima da média
  return '#F39200'                                // laranja MRV — dentro da faixa
}

function formatarMoeda(valor: number): string {
  return `R$ ${valor.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function portalColor(portal: string): string {
  const map: Record<string, string> = {
    vivareal: '#0B5A42',
    zapimoveis: '#F39200',
    olx: '#6366f1',
    imovelweb: '#0284c7',
    netimoveis: '#7c3aed',
    mercadolivre: '#ca8a04',
  }
  return map[portal] ?? '#4A7A65'
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload?: Empreendimento }[] }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-card p-3 shadow-card-hover text-sm max-w-[220px]">
      <p className="font-semibold text-mrv-text mb-0.5 leading-snug text-xs line-clamp-2">{d.nome_anuncio}</p>
      {d.construtora && <p className="text-mrv-text-muted text-[10px] mb-2">{d.construtora}</p>}
      <div className="space-y-1 text-[11px]">
        <p className="text-mrv-text-muted">Total: <span className="font-semibold text-mrv-text">{formatarMoeda(d.preco)}</span></p>
        <p className="text-mrv-text-muted">Área: <span className="font-semibold text-mrv-text">{d.area_m2} m²</span></p>
        <p className="font-bold text-mrv-orange text-sm mt-1">{formatarMoeda(d.preco_m2)}<span className="text-mrv-text-muted font-normal text-[10px]">/m²</span></p>
        {d.variacao_mrv_pct != null && (
          <p className={`font-semibold text-[10px] ${d.variacao_mrv_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {d.variacao_mrv_pct >= 0 ? '▲' : '▼'} {Math.abs(d.variacao_mrv_pct).toFixed(1)}% vs MRV
          </p>
        )}
      </div>
      <div className="mt-2 pt-2 border-t border-mrv-border">
        <span className="text-[10px] px-2 py-0.5 rounded-full text-white font-medium" style={{ background: portalColor(d.portal) }}>
          {d.portal}
        </span>
      </div>
    </div>
  )
}

export function PriceChart({ dados }: Props) {
  if (!dados.empreendimentos.length) return null

  const chartData = dados.empreendimentos.slice(0, 24).map(e => ({
    ...e,
    nome_curto: e.nome_anuncio.slice(0, 12),
  }))

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 mb-5">
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em]">
          Comparativo Preço/m²
        </h2>
        <div className="flex gap-4 text-[10px] text-mrv-text-muted">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm inline-block bg-emerald-500" />
            Abaixo da média
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm inline-block bg-mrv-orange" />
            Dentro da faixa
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm inline-block bg-red-500" />
            Acima da média
          </span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1A4A35" />
          <XAxis
            dataKey="nome_curto"
            tick={{ fontSize: 10, fill: '#4A7A65' }}
            angle={-40}
            textAnchor="end"
            interval={0}
            axisLine={{ stroke: '#1A4A35' }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v) => `R$ ${(v / 1000).toFixed(0)}k`}
            tick={{ fontSize: 10, fill: '#4A7A65' }}
            width={72}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(11,90,66,0.1)' }} />

          {/* Linha de média do mercado */}
          <ReferenceLine
            y={dados.preco_m2_medio}
            stroke="#7BA898"
            strokeDasharray="6 3"
            strokeWidth={1}
            label={{ value: 'Média', position: 'insideTopRight', fontSize: 9, fill: '#7BA898' }}
          />

          {/* Linha referencial MRV */}
          {dados.preco_m2_mrv && (
            <ReferenceLine
              y={dados.preco_m2_mrv}
              stroke="#F39200"
              strokeDasharray="6 3"
              strokeWidth={1.5}
              label={{ value: 'Ref. MRV', position: 'insideBottomRight', fontSize: 9, fill: '#F39200' }}
            />
          )}

          <Bar dataKey="preco_m2" radius={[3, 3, 0, 0]} maxBarSize={36}>
            {chartData.map((entry, index) => (
              <Cell key={index} fill={corBarra(entry.preco_m2, dados.preco_m2_medio)} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
