import { Edit3, TrendingDown, TrendingUp, Minus } from 'lucide-react'
import type { BuscaResponse } from '../types'

interface Props {
  dados: BuscaResponse
  onEditarMRV?: () => void
}

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function calcularDelta(precoMRV: number, media: number): { pct: number; texto: string; positivo: boolean } {
  const pct = ((precoMRV - media) / media) * 100
  return {
    pct,
    texto: `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`,
    positivo: pct <= 0, // MRV abaixo da média é positivo (mais competitivo)
  }
}

export function KpiBar({ dados, onEditarMRV }: Props) {
  const empMin = dados.empreendimentos.find(e => e.preco_m2 === dados.preco_m2_min)
  const empMax = dados.empreendimentos.find(e => e.preco_m2 === dados.preco_m2_max)
  // Buscas antigas do cache não têm mediana gravada — cai para a média.
  const precoReferencia = dados.preco_m2_mediana || dados.preco_m2_medio
  const delta = dados.preco_m2_mrv ? calcularDelta(dados.preco_m2_mrv, precoReferencia) : null

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">

      {/* Total de Concorrentes — destaque primário */}
      <div className="bg-mrv-green border border-mrv-green-light rounded-card shadow-kpi p-5 flex flex-col justify-between relative overflow-hidden">
        {/* Detalhe de fundo sutil */}
        <div className="absolute -right-4 -top-4 w-20 h-20 rounded-full bg-white/5" />
        <div className="absolute -right-2 -top-2 w-10 h-10 rounded-full bg-white/5" />
        <div>
          <p className="text-[10px] font-semibold text-white/60 uppercase tracking-[0.12em] mb-3">
            Concorrentes
          </p>
          <p className="font-data font-bold text-white leading-none" style={{ fontSize: '2.75rem', letterSpacing: '-0.03em' }}>
            {dados.total}
          </p>
        </div>
        <p className="text-[10px] text-white/50 mt-3 tracking-wide">
          {dados.tempo_coleta_segundos}s · varredura completa
        </p>
      </div>

      {/* Preço/m² mediano — número de referência.
          Mediana e não média: um único anúncio com área agregada ou erro de
          parsing desloca a média, mas não a mediana. */}
      <div className="bg-mrv-surface border border-mrv-border rounded-card shadow-kpi p-5 flex flex-col justify-between">
        <div>
          <p className="text-[10px] font-semibold text-mrv-text-dim uppercase tracking-[0.12em] mb-3">
            Preço/m² mediano
          </p>
          <p className="font-data font-bold text-mrv-text leading-none text-[1.65rem]" style={{ letterSpacing: '-0.02em' }}>
            {formatarMoeda(precoReferencia)}
          </p>
        </div>
        <p className="text-[10px] text-mrv-text-muted mt-3 flex items-center gap-1">
          <Minus size={10} className="text-mrv-text-dim" />
          média {formatarMoeda(dados.preco_m2_medio)}
        </p>
      </div>

      {/* Menor preço/m² */}
      <div className="bg-mrv-surface border border-mrv-border rounded-card shadow-kpi p-5 flex flex-col justify-between">
        <div>
          <p className="text-[10px] font-semibold text-mrv-text-dim uppercase tracking-[0.12em] mb-3">
            Menor preço/m²
          </p>
          <p className="font-data font-bold text-mrv-price-low leading-none text-[1.65rem]" style={{ letterSpacing: '-0.02em' }}>
            {formatarMoeda(dados.preco_m2_min)}
          </p>
        </div>
        <p className="text-[10px] text-mrv-text-muted mt-3 flex items-center gap-1 truncate">
          <TrendingDown size={10} className="text-mrv-price-low flex-shrink-0" />
          <span className="truncate">{empMin?.nome_anuncio?.slice(0, 20) ?? '—'}</span>
        </p>
      </div>

      {/* Maior preço/m² */}
      <div className="bg-mrv-surface border border-mrv-border rounded-card shadow-kpi p-5 flex flex-col justify-between">
        <div>
          <p className="text-[10px] font-semibold text-mrv-text-dim uppercase tracking-[0.12em] mb-3">
            Maior preço/m²
          </p>
          <p className="font-data font-bold text-mrv-price-high leading-none text-[1.65rem]" style={{ letterSpacing: '-0.02em' }}>
            {formatarMoeda(dados.preco_m2_max)}
          </p>
        </div>
        <p className="text-[10px] text-mrv-text-muted mt-3 flex items-center gap-1 truncate">
          <TrendingUp size={10} className="text-mrv-price-high flex-shrink-0" />
          <span className="truncate">{empMax?.nome_anuncio?.slice(0, 20) ?? '—'}</span>
        </p>
      </div>

      {/* Referencial MRV */}
      <div className="bg-mrv-surface border border-mrv-orange/30 rounded-card shadow-kpi p-5 flex flex-col justify-between relative">
        <div>
          <div className="flex items-start justify-between mb-3">
            <p className="text-[10px] font-semibold text-mrv-text-dim uppercase tracking-[0.12em]">
              Ref. MRV
            </p>
            {onEditarMRV && (
              <button
                type="button"
                onClick={onEditarMRV}
                className="text-mrv-text-dim hover:text-mrv-orange transition-colors -mt-0.5"
                title="Editar referencial MRV"
              >
                <Edit3 size={12} />
              </button>
            )}
          </div>
          {dados.preco_m2_mrv ? (
            <p className="font-data font-bold text-mrv-orange leading-none text-[1.65rem]" style={{ letterSpacing: '-0.02em' }}>
              {formatarMoeda(dados.preco_m2_mrv)}
            </p>
          ) : (
            <div>
              <p className="text-mrv-text-muted text-sm font-medium">Não cadastrado</p>
              {onEditarMRV && (
                <button
                  type="button"
                  onClick={onEditarMRV}
                  className="text-[11px] text-mrv-orange font-semibold mt-2 hover:underline"
                >
                  + Cadastrar referencial
                </button>
              )}
            </div>
          )}
        </div>
        {delta && (
          <div className={`mt-3 flex items-center gap-1.5 text-[10px] font-semibold ${delta.positivo ? 'text-mrv-price-low' : 'text-mrv-price-high'}`}>
            {delta.positivo
              ? <TrendingDown size={10} />
              : <TrendingUp size={10} />
            }
            <span>{delta.texto} vs. mediana</span>
          </div>
        )}
        {dados.preco_m2_mrv && !delta && (
          <p className="text-[10px] text-mrv-text-muted mt-3">preço/m² MRV</p>
        )}
        {/* Acento laranja no topo */}
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-mrv-orange rounded-t-card" />
      </div>

    </div>
  )
}
