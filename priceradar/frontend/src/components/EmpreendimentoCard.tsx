import { Building2, ChevronRight, MapPin } from 'lucide-react'
import { LABEL_PORTAL } from '../data/portais'
import type { GrupoEmpreendimento, NivelGrupo, SinalGrupo } from '../types'
import { desvioPercentual, faixaPorDesvio, rotuloDesvio } from '../utils/posicionamento'
import { FotoCarrossel } from './FotoCarrossel'

interface Props {
  grupo: GrupoEmpreendimento
  precoM2Medio: number
  onAbrir: (grupo: GrupoEmpreendimento) => void
  indice?: number
}

const STAGGER_MAX_INDICE = 10
const STAGGER_STEP_MS = 25

export const ROTULO_SINAL: Record<SinalGrupo, string> = {
  endereco: 'mesmo endereço',
  coordenada: 'mesma localização no mapa',
  nome: 'mesmo nome de empreendimento',
}

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function faixa(min: number | null, max: number | null, sufixo = ''): string | null {
  if (min == null || max == null) return null
  return Math.round(min) === Math.round(max)
    ? `${Math.round(min)}${sufixo}`
    : `${Math.round(min)}–${Math.round(max)}${sufixo}`
}

/** Título do prédio: o nome quando há, senão o endereço — nunca inventa. */
export function tituloGrupo(g: GrupoEmpreendimento): string {
  return g.nome || g.endereco || (g.bairro ? `Prédio no ${g.bairro}` : 'Empreendimento sem nome')
}

/** O que cada nível prova — rótulo das abas, dos selos e do dossiê. */
export const NIVEL_INFO: Record<NivelGrupo, { rotulo: string; cor: string; explicacao: string }> = {
  mesmo_predio: {
    rotulo: 'Mesmo prédio',
    cor: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    explicacao: 'Rua e número idênticos: o exato mesmo prédio.',
  },
  mesmo_local: {
    rotulo: 'Mesmo local',
    cor: 'bg-sky-900/40 text-sky-300 border-sky-700/40',
    explicacao: 'Mesmo ponto do mapa publicado pelo portal, sem número para confirmar. Provável, não prova: o portal às vezes põe prédios vizinhos no mesmo ponto.',
  },
  mesmo_nome: {
    rotulo: 'Mesmo nome',
    cor: 'bg-amber-900/40 text-amber-300 border-amber-700/40',
    explicacao: 'Ligados só pelo nome do empreendimento. Confira: pode ser um condomínio com várias torres ou dois empreendimentos com o mesmo nome.',
  },
}

/** Nível de prova do grupo, com o porquê no tooltip — palpite não passa por fato. */
export function SeloNivel({ grupo }: { grupo: GrupoEmpreendimento }) {
  const info = NIVEL_INFO[grupo.nivel] ?? NIVEL_INFO.mesmo_nome
  const motivo = grupo.sinais.map(s => ROTULO_SINAL[s]).join(' + ')
  return (
    <span
      className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${info.cor}`}
      title={`${info.explicacao}${motivo ? ` Ligados por: ${motivo}.` : ''}`}
    >
      {info.rotulo}
    </span>
  )
}

export function SeloLancamento({ valor }: { valor: boolean | null | undefined }) {
  if (valor !== true) return null
  return (
    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-orange-900/50 text-orange-300 border border-orange-700/40"
          title="URL de lançamento do portal ou anúncio que declara obra/na planta">
      Lançamento
    </span>
  )
}

export function EmpreendimentoCard({ grupo: g, precoM2Medio, onAbrir, indice = 0 }: Props) {
  const pct = desvioPercentual(g.preco_m2_mediana, precoM2Medio)
  const pos = { label: rotuloDesvio(pct), ...faixaPorDesvio(pct) }
  const areas = faixa(g.area_min, g.area_max, ' m²')
  const quartos = g.quartos.length ? `${g.quartos.join('/')} qto${g.quartos[g.quartos.length - 1] === 1 ? '' : 's'}` : null
  const titulo = tituloGrupo(g)

  return (
    // div, não button: o carrossel de fotos tem botões próprios, e botão
    // dentro de botão é HTML inválido. O teclado usa o "Ver dossiê" abaixo.
    <div
      onClick={() => onAbrir(g)}
      className="cursor-pointer text-left bg-mrv-surface border border-mrv-border rounded-card shadow-card hover:shadow-card-hover hover:border-mrv-green/60 transition-all duration-200 overflow-hidden flex group motion-safe:animate-fade-up"
      style={{ animationDelay: `${Math.min(indice, STAGGER_MAX_INDICE) * STAGGER_STEP_MS}ms` }}
    >
      <div className={`w-1 flex-shrink-0 ${pos.barColor} opacity-80 group-hover:opacity-100 transition-opacity`} />
      <div className="flex-1 flex flex-col min-w-0">
        {/* O clique na foto é do carrossel (lightbox), não do card. */}
        <div onClick={e => e.stopPropagation()}>
          <FotoCarrossel fotos={g.foto ? [g.foto] : []} titulo={titulo} />
        </div>

        <div className="flex-1 p-4 flex flex-col min-w-0">
          <div className="flex items-start gap-2 mb-2">
            <Building2 size={14} className="text-mrv-text-dim mt-0.5 flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <h3 className="font-bold text-mrv-text text-sm leading-snug line-clamp-1 tracking-tight">{titulo}</h3>
              {g.nome && g.endereco && (
                <p className="text-[11px] text-mrv-text-muted line-clamp-1 mt-0.5">{g.endereco}</p>
              )}
            </div>
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onAbrir(g) }}
              className="flex items-center gap-0.5 text-[11px] font-semibold text-mrv-text-muted border border-mrv-border px-2 py-1 rounded-card hover:border-mrv-green hover:text-mrv-text transition-colors whitespace-nowrap flex-shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-mrv-green"
              aria-label={`Ver o dossiê de ${titulo}`}
            >
              Ver dossiê <ChevronRight size={12} />
            </button>
          </div>

          <div className="flex items-center flex-wrap gap-1.5 mb-3">
            <SeloNivel grupo={g} />
            <SeloLancamento valor={g.eh_lancamento} />
            {g.construtora && (
              <span className="text-[10px] font-medium text-mrv-text-muted bg-mrv-surface-2/60 px-2 py-0.5 rounded-full">{g.construtora}</span>
            )}
            {g.bairro && (
              <span className="text-[10px] font-medium text-mrv-text-muted flex items-center gap-0.5">
                <MapPin size={9} />{g.bairro}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3 text-[11px] text-mrv-text-muted py-2.5 border-t border-b border-mrv-border/50 mb-3">
            <span title="A mesma unidade anunciada mais de uma vez conta uma vez">
              <strong className="text-mrv-text">{g.n_anuncios}</strong> anúncios
              {g.n_unidades !== g.n_anuncios && <> · {g.n_unidades} unidade{g.n_unidades === 1 ? '' : 's'}</>}
            </span>
            {areas && <span>{areas}</span>}
            {quartos && <span>{quartos}</span>}
          </div>
          {g.n_provaveis > 0 && (
            <p className="-mt-2 mb-3 text-[10px] text-mrv-text-dim"
               title="Anúncios sem número no mesmo ponto do mapa (ou com o nome deste prédio no mesmo bairro). Aparecem no dossiê, mas não entram no preço.">
              +{g.n_provaveis} provável{g.n_provaveis === 1 ? '' : 'is'} (sem número no anúncio) — fora do preço
            </p>
          )}

          <div className="mt-auto flex items-end justify-between gap-2">
            <div>
              <p className="text-[10px] text-mrv-text-dim mb-1 tracking-wide">Preço/m² mediano do prédio</p>
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-data font-bold text-mrv-text text-[1.2rem] leading-none" style={{ letterSpacing: '-0.02em' }}>
                  {formatarMoeda(g.preco_m2_mediana)}
                </span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${pos.pctBg} ${pos.pctColor}`}>{pos.label}</span>
              </div>
              {g.preco_m2_min !== g.preco_m2_max && (
                <p className="text-[10px] text-mrv-text-dim mt-1">
                  {formatarMoeda(g.preco_m2_min)} a {formatarMoeda(g.preco_m2_max)}
                </p>
              )}
            </div>
            <p className="text-[10px] text-mrv-text-dim text-right">{g.portais.map(LABEL_PORTAL).join(' · ')}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
