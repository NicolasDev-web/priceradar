import { Bath, BedDouble, Car, ExternalLink, MapPin } from 'lucide-react'
import type { Empreendimento } from '../types'
import { VariacaoMRVBadge } from './VariacaoMRVBadge'

interface Props {
  empreendimento: Empreendimento
  precoM2Medio: number
}

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

/** Retorna cor e label baseados no desvio percentual em relação à média */
function calcularPosicionamento(preco_m2: number, media: number): {
  pct: number
  label: string
  barColor: string        // cor da barra lateral (Tailwind bg)
  pctColor: string        // cor do texto de variação
  pctBg: string           // fundo do badge de variação
} {
  const pct = ((preco_m2 - media) / media) * 100
  if (pct < -8) return {
    pct,
    label: `${pct.toFixed(1)}%`,
    barColor: 'bg-emerald-500',
    pctColor: 'text-emerald-400',
    pctBg: 'bg-emerald-950/70 border border-emerald-800/50',
  }
  if (pct < -2) return {
    pct,
    label: `${pct.toFixed(1)}%`,
    barColor: 'bg-emerald-700',
    pctColor: 'text-emerald-500',
    pctBg: 'bg-emerald-950/50 border border-emerald-900/50',
  }
  if (pct <= 2) return {
    pct,
    label: `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`,
    barColor: 'bg-amber-500',
    pctColor: 'text-amber-400',
    pctBg: 'bg-amber-950/70 border border-amber-800/50',
  }
  if (pct <= 8) return {
    pct,
    label: `+${pct.toFixed(1)}%`,
    barColor: 'bg-orange-600',
    pctColor: 'text-orange-400',
    pctBg: 'bg-orange-950/60 border border-orange-800/50',
  }
  return {
    pct,
    label: `+${pct.toFixed(1)}%`,
    barColor: 'bg-red-500',
    pctColor: 'text-red-400',
    pctBg: 'bg-red-950/60 border border-red-800/50',
  }
}

const PORTAL_MAP: Record<string, { label: string; color: string }> = {
  vivareal:     { label: 'VivaReal',      color: 'bg-emerald-900/60 text-emerald-300' },
  zapimoveis:   { label: 'ZAP',           color: 'bg-amber-900/60 text-amber-300' },
  olx:          { label: 'OLX',           color: 'bg-indigo-900/60 text-indigo-300' },
  imovelweb:    { label: 'ImovelWeb',     color: 'bg-sky-900/60 text-sky-300' },
  netimoveis:   { label: 'NetImóveis',    color: 'bg-violet-900/60 text-violet-300' },
  mercadolivre: { label: 'Mercado Livre', color: 'bg-yellow-900/60 text-yellow-300' },
}

/** Indicador visual do rf_score (0-1): barra + rótulo de confiabilidade */
function RfScoreIndicator({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const barColor =
    score >= 0.75 ? 'bg-emerald-500' :
    score >= 0.5  ? 'bg-amber-500'   :
                    'bg-red-500'
  const label =
    score >= 0.75 ? 'Alta confiança' :
    score >= 0.5  ? 'Média confiança' :
                    'Baixa confiança'
  const textColor =
    score >= 0.75 ? 'text-emerald-400' :
    score >= 0.5  ? 'text-amber-400'   :
                    'text-red-400'

  return (
    <div className="flex items-center gap-2" title={`RF Score: ${score.toFixed(2)} — ${label}`}>
      {/* Barra de progresso */}
      <div className="w-14 h-1.5 bg-mrv-surface-2 rounded-full overflow-hidden flex-shrink-0">
        <div
          className={`h-full rounded-full ${barColor} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-[10px] font-semibold ${textColor}`}>{pct}%</span>
    </div>
  )
}

export function ResultCard({ empreendimento: e, precoM2Medio }: Props) {
  const pos = calcularPosicionamento(e.preco_m2, precoM2Medio)
  const portalCfg = PORTAL_MAP[e.portal] ?? { label: e.portal, color: 'bg-mrv-surface-2 text-mrv-text-muted' }

  const nomePrincipal =
    e.nome_empreendimento && e.nome_empreendimento !== e.nome_anuncio
      ? e.nome_empreendimento
      : e.nome_anuncio
  const nomeSecundario =
    e.nome_empreendimento && e.nome_empreendimento !== e.nome_anuncio
      ? e.nome_anuncio
      : null

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-card shadow-card hover:shadow-card-hover hover:border-mrv-surface-2 transition-all duration-200 overflow-hidden flex group">

      {/* Barra lateral de posicionamento — encode a informação de preço relativo */}
      <div className={`w-1 flex-shrink-0 ${pos.barColor} opacity-80 group-hover:opacity-100 transition-opacity`} />

      <div className="flex-1 p-4 flex flex-col min-w-0">

        {/* Header: nome + preço total */}
        <div className="flex justify-between items-start gap-2 mb-2.5">
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-mrv-text text-sm leading-snug line-clamp-1 tracking-tight">
              {nomePrincipal}
            </h3>
            {nomeSecundario && (
              <p className="text-[11px] text-mrv-text-muted line-clamp-1 mt-0.5 leading-snug">
                {nomeSecundario}
              </p>
            )}
          </div>
          <span className="font-data font-bold text-mrv-text text-sm whitespace-nowrap ml-1 flex-shrink-0">
            {formatarMoeda(e.preco)}
          </span>
        </div>

        {/* Meta: portal + construtora + bairro */}
        <div className="flex items-center flex-wrap gap-1.5 mb-3">
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${portalCfg.color}`}>
            {portalCfg.label}
          </span>
          {e.construtora && (
            <span className="text-[10px] font-medium text-mrv-text-muted bg-mrv-surface-2/60 px-2 py-0.5 rounded-full">
              {e.construtora}
            </span>
          )}
          {e.bairro && (
            <span className="text-[10px] text-mrv-text-dim flex items-center gap-0.5">
              <MapPin size={9} />
              {e.bairro}
            </span>
          )}
          <span className="text-[10px] text-mrv-text-dim ml-auto flex-shrink-0">{e.area_m2} m²</span>
        </div>

        {/* Detalhes: quartos, banheiros, vagas */}
        <div className="flex items-center gap-3.5 text-[11px] text-mrv-text-muted py-2.5 border-t border-b border-mrv-border/50 mb-3">
          {e.quartos != null && (
            <span className="flex items-center gap-1">
              <BedDouble size={11} className="text-mrv-text-dim" />
              {e.quartos} qto{e.quartos !== 1 ? 's' : ''}
            </span>
          )}
          {e.banheiros != null && (
            <span className="flex items-center gap-1">
              <Bath size={11} className="text-mrv-text-dim" />
              {e.banheiros} bnh
            </span>
          )}
          {e.vagas != null && (
            <span className="flex items-center gap-1">
              <Car size={11} className="text-mrv-text-dim" />
              {e.vagas} vaga{e.vagas !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {/* Rodapé: preço/m² + rf_score + link */}
        <div className="mt-auto">
          {/* Linha 1: preço/m² e variação */}
          <div className="flex items-end justify-between gap-2 mb-2">
            <div>
              <p className="text-[10px] text-mrv-text-dim mb-1 tracking-wide">Preço/m²</p>
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-data font-bold text-mrv-text text-[1.2rem] leading-none" style={{ letterSpacing: '-0.02em' }}>
                  {formatarMoeda(e.preco_m2)}
                </span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${pos.pctBg} ${pos.pctColor}`}>
                  {pos.label}
                </span>
              </div>
              {/* Badge variação MRV */}
              {e.variacao_mrv_pct != null && (
                <div className="mt-1.5">
                  <VariacaoMRVBadge variacao={e.variacao_mrv_pct} />
                </div>
              )}
            </div>

            <a
              href={e.url_anuncio}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[11px] font-semibold text-mrv-text-muted border border-mrv-border px-2.5 py-1.5 rounded-card hover:border-mrv-green hover:text-mrv-text transition-colors whitespace-nowrap flex-shrink-0"
            >
              Ver <ExternalLink size={10} />
            </a>
          </div>

          {/* Linha 2: rf_score (se disponível) */}
          {e.rf_score != null && (
            <div className="flex items-center gap-2 pt-2 border-t border-mrv-border/40">
              <span className="text-[10px] text-mrv-text-dim tracking-wide">Confiabilidade RF</span>
              <RfScoreIndicator score={e.rf_score} />
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
