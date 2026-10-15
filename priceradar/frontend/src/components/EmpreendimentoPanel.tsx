import axios from 'axios'
import { AlertTriangle, Building2, ChevronDown, ExternalLink, MapPin, RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { buscarDossie, procurarEmpreendimento } from '../api/client'
import { LABEL_PORTAL, PORTAL_CONFIG } from '../data/portais'
import { useDelayedUnmount } from '../hooks/useDelayedUnmount'
import type {
  AnuncioDossie,
  DossieEmpreendimento,
  GrupoEmpreendimento,
  MotivoAnuncio,
  PontoEvolucaoBairro,
  ProcurarEmpreendimentoRequest,
} from '../types'
import { descricaoSemana, formatarMoeda, rotuloSemana } from '../utils/evolucao'
import { SeloConfianca, SeloLancamento, tituloGrupo } from './EmpreendimentoCard'

// Mesma duração do HistoricoPanel (`drawer-out` no tailwind.config.ts).
const DRAWER_EXIT_MS = 180
const COR_LINHA = '#0B5A42'
const COR_PONTO = '#0D6B4F'

/** O que abrir: um grupo da busca (pelo id) ou uma procura por nome/endereço. */
export type PedidoDossie =
  | { tipo: 'grupo'; grupoId: string; titulo?: string }
  | { tipo: 'procura'; params: ProcurarEmpreendimentoRequest }

interface Props {
  isOpen: boolean
  cidade: string
  pedido: PedidoDossie | null
  /** Mediana da busca atual, para dizer onde o prédio está em relação à praça. */
  precoM2Referencia?: number | null
  onAbrirGrupo: (grupo: GrupoEmpreendimento) => void
  onFechar: () => void
}

const ROTULO_MOTIVO: Record<MotivoAnuncio, string> = {
  endereco: 'mesmo endereço',
  coordenada: 'mesmo ponto no mapa',
  mesmo_predio: 'mesmo prédio',
  nome: 'mesmo nome',
  texto: 'nome citado no anúncio',
  rua: 'mesma rua',
}

function dataCurta(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function pct(v: number | null): string | null {
  if (v == null) return null
  return `${v > 0 ? '+' : ''}${v.toFixed(1).replace('.', ',')}%`
}

function LinhaAnuncio({ a }: { a: AnuncioDossie }) {
  const cfg = PORTAL_CONFIG[a.portal]
  const variacao = pct(a.variacao_vs_grupo_pct)
  return (
    <li className={`flex items-start gap-3 py-2.5 border-b border-mrv-border/40 last:border-0 ${a.ativo ? '' : 'opacity-60'}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap mb-1">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${cfg?.color ?? 'bg-mrv-surface-2 text-mrv-text-muted'}`}>
            {LABEL_PORTAL(a.portal)}
          </span>
          {!a.ativo && (
            <span className="text-[10px] text-mrv-text-dim" title="Não apareceu nas coletas das últimas 2 semanas">
              fora do ar desde {dataCurta(a.ultima_vez)}
            </span>
          )}
          {a.motivo && (
            <span className="text-[10px] text-mrv-text-dim">· {ROTULO_MOTIVO[a.motivo]}</span>
          )}
        </div>
        <p className="text-[11px] text-mrv-text-muted line-clamp-1" title={a.nome_anuncio ?? ''}>{a.nome_anuncio}</p>
        <p className="text-[10px] text-mrv-text-dim mt-0.5">
          {Math.round(a.area_m2)} m²{a.quartos != null && ` · ${a.quartos} qto${a.quartos === 1 ? '' : 's'}`}
          {' · '}{formatarMoeda(a.preco)}
          {a.bairro && ` · ${a.bairro}`}
          {' · visto em '}{dataCurta(a.primeira_vez)}
        </p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className="font-data font-bold text-mrv-text text-sm">{formatarMoeda(a.preco_m2)}</p>
        {variacao && (
          <p className={`text-[10px] font-semibold ${a.variacao_vs_grupo_pct! < 0 ? 'text-mrv-price-low' : 'text-mrv-price-high'}`}
             title="Diferença para a mediana do prédio">
            {variacao} vs prédio
          </p>
        )}
        <a
          href={a.url_anuncio}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 text-[10px] text-mrv-text-muted hover:text-mrv-text mt-1"
        >
          abrir <ExternalLink size={9} />
        </a>
      </div>
    </li>
  )
}

function Estatistica({ rotulo, valor, detalhe }: { rotulo: string; valor: string; detalhe?: string | null }) {
  return (
    <div className="bg-mrv-surface-2/40 border border-mrv-border rounded-card px-3 py-2.5">
      <p className="text-[10px] font-semibold text-mrv-text-dim uppercase tracking-[0.1em] mb-1">{rotulo}</p>
      <p className="font-data font-bold text-mrv-text text-base leading-none">{valor}</p>
      {detalhe && <p className="text-[10px] text-mrv-text-muted mt-1">{detalhe}</p>}
    </div>
  )
}

interface PropsTooltip {
  active?: boolean
  payload?: { payload: PontoEvolucaoBairro }[]
}

function TooltipSerie({ active, payload }: PropsTooltip) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-panel border border-mrv-border bg-mrv-surface-2 px-3 py-2 text-[11px] text-mrv-text shadow-card">
      <div className="mb-1 text-mrv-text-muted">{descricaoSemana(p.semana)}</div>
      <div className="font-data font-semibold">{formatarMoeda(p.preco_m2_mediana)}/m²</div>
      <div className={`mt-0.5 text-[10px] ${p.pouco_confiavel ? 'text-amber-300/90' : 'text-mrv-text-muted'}`}>
        Mediana de {p.n} anúncio{p.n === 1 ? '' : 's'} vistos nessa semana
        {p.pouco_confiavel ? ' · poucos anúncios, o valor pode oscilar mais' : ''}
      </div>
    </div>
  )
}

function Serie({ dados }: { dados: DossieEmpreendimento }) {
  if (dados.serie.length < 2) {
    return (
      <p className="text-[11px] text-mrv-text-dim">
        Evolução aparece a partir de duas semanas com coleta deste prédio.
      </p>
    )
  }
  const pontos = dados.serie.map(p => ({ ...p, semana_fmt: rotuloSemana(p.semana) }))
  return (
    <div className="h-36">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pontos} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#1f3a2d" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="semana_fmt" tick={{ fontSize: 10, fill: '#8aa597' }} tickLine={false} axisLine={false} />
          <YAxis tickFormatter={formatarMoeda} tick={{ fontSize: 10, fill: '#8aa597' }} tickLine={false} axisLine={false} width={72} tickCount={3} domain={['dataMin - 200', 'dataMax + 200']} />
          <Tooltip content={<TooltipSerie />} />
          <Line type="linear" dataKey="preco_m2_mediana" stroke={COR_LINHA} strokeWidth={2}
                dot={{ r: 3, fill: COR_PONTO }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function EmpreendimentoPanel({ isOpen, cidade, pedido, precoM2Referencia, onAbrirGrupo, onFechar }: Props) {
  const mounted = useDelayedUnmount(isOpen, DRAWER_EXIT_MS)
  const [dados, setDados] = useState<DossieEmpreendimento | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [verProvaveis, setVerProvaveis] = useState(false)
  // Coleta direcionada pedida pelo botão do painel (só na procura).
  const [coletar, setColetar] = useState(false)

  useEffect(() => {
    setColetar(false)
  }, [pedido])

  useEffect(() => {
    if (!pedido) return
    const controller = new AbortController()
    setCarregando(true)
    setErro(null)
    setDados(null)
    setVerProvaveis(false)
    const chamada = pedido.tipo === 'grupo'
      ? buscarDossie(cidade, pedido.grupoId)
      : procurarEmpreendimento({ ...pedido.params, coletar }, controller.signal)
    chamada
      .then(setDados)
      .catch((e: unknown) => {
        if (axios.isCancel(e)) return
        const status = (e as { response?: { status?: number } }).response?.status
        setErro(status === 404
          ? 'Este empreendimento ainda não está no histórico — a busca que o encontrou pode não ter sido gravada.'
          : 'Não foi possível carregar o dossiê. Verifique se o servidor está rodando.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false)
      })
    return () => controller.abort()
  }, [pedido, cidade, coletar])

  if (!mounted) return null

  const g = dados?.grupo ?? null
  const procura = pedido?.tipo === 'procura' ? pedido.params : null
  const titulo = g ? tituloGrupo(g)
    : procura ? `Procurando “${procura.nome || procura.endereco}”`
    : pedido?.tipo === 'grupo' ? (pedido.titulo ?? 'Empreendimento') : 'Empreendimento'
  const vsPraca = g && precoM2Referencia
    ? ((g.preco_m2_mediana - precoM2Referencia) / precoM2Referencia) * 100
    : null

  return (
    <div
      role="dialog"
      aria-label={`Dossiê: ${titulo}`}
      className={`fixed inset-y-0 right-0 w-full max-w-lg bg-mrv-surface border-l border-mrv-border z-40 flex flex-col shadow-[-4px_0_32px_rgba(0,0,0,0.5)] ${
        isOpen ? 'motion-safe:animate-drawer-in' : 'motion-safe:animate-drawer-out'
      }`}
    >
      <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-mrv-border">
        <div className="flex items-start gap-2 min-w-0">
          <Building2 size={15} className="text-mrv-text-muted mt-0.5 flex-shrink-0" />
          <div className="min-w-0">
            <h2 className="font-bold text-sm tracking-tight text-mrv-text line-clamp-2">{titulo}</h2>
            {g?.nome && g.endereco && <p className="text-[11px] text-mrv-text-muted mt-0.5">{g.endereco}</p>}
            {g?.bairro && (
              <p className="text-[11px] text-mrv-text-dim flex items-center gap-0.5 mt-0.5"><MapPin size={9} />{g.bairro}</p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onFechar}
          aria-label="Fechar"
          className="text-mrv-text-dim hover:text-mrv-text transition-colors p-1 rounded hover:bg-mrv-surface-2"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {carregando && (
          <p className="text-sm text-mrv-text-muted">
            {coletar ? 'Coletando anúncios no bairro e procurando — pode levar um minuto…' : 'Carregando o histórico…'}
          </p>
        )}
        {erro && <p className="text-sm text-red-300">{erro}</p>}

        {dados && !carregando && (
          <>
            {dados.alvo && dados.alvo.endereco && (
              <p className="text-[11px] text-mrv-text-muted">
                {dados.alvo.endereco_encontrado
                  ? <>Endereço no mapa: <span className="text-mrv-text">{dados.alvo.endereco_encontrado}</span>
                      {!dados.alvo.geocodificacao_precisa && ' — só a rua foi localizada; a busca pelo ponto no mapa não foi usada.'}</>
                  : 'O endereço não foi localizado no mapa; comparado só como texto.'}
              </p>
            )}
            {dados.coleta === 'sem_bairro' && (
              <p className="text-[11px] text-amber-300">
                Coleta não feita: não foi possível descobrir o bairro do endereço. Busque pelo formulário com o bairro.
              </p>
            )}

            {dados.aviso && (
              <div className="flex items-start gap-2 bg-amber-950/40 border border-amber-800/40 rounded-card px-3 py-2.5">
                <AlertTriangle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
                <p className="text-[11px] text-amber-200/90">{dados.aviso}</p>
              </div>
            )}

            {g ? (
              <>
                <div className="flex items-center gap-1.5 flex-wrap">
                  <SeloConfianca grupo={g} />
                  <SeloLancamento valor={g.eh_lancamento} />
                  {g.construtora && (
                    <span className="text-[10px] font-medium text-mrv-text-muted bg-mrv-surface-2/60 px-2 py-0.5 rounded-full">{g.construtora}</span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <Estatistica
                    rotulo="Preço/m² mediano"
                    valor={formatarMoeda(g.preco_m2_mediana)}
                    detalhe={vsPraca != null ? `${pct(vsPraca)} vs mediana da busca` : `média ${formatarMoeda(g.preco_m2_medio)}`}
                  />
                  <Estatistica
                    rotulo="Faixa de preço/m²"
                    valor={`${formatarMoeda(g.preco_m2_min)}`}
                    detalhe={`até ${formatarMoeda(g.preco_m2_max)}`}
                  />
                  <Estatistica
                    rotulo="Anúncios"
                    valor={String(g.n_anuncios)}
                    detalhe={`${g.n_unidades} unidade${g.n_unidades === 1 ? '' : 's'} · ${dados.ativos} no ar`}
                  />
                  <Estatistica
                    rotulo="Tipologia"
                    valor={g.area_min != null && g.area_max != null
                      ? (Math.round(g.area_min) === Math.round(g.area_max) ? `${Math.round(g.area_min)} m²` : `${Math.round(g.area_min)}–${Math.round(g.area_max)} m²`)
                      : '—'}
                    detalhe={g.quartos.length ? `${g.quartos.join('/')} quartos` : null}
                  />
                </div>
                {g.n_anuncios < 3 && (
                  <p className="text-[11px] text-amber-300/90">
                    Só {g.n_anuncios} anúncio{g.n_anuncios === 1 ? '' : 's'}: use como indicativo, não como preço do prédio.
                  </p>
                )}

                <section>
                  <h3 className="text-[10px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] mb-2">Evolução (mediana semanal)</h3>
                  <Serie dados={dados} />
                </section>

                <section>
                  <h3 className="text-[10px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] mb-1">
                    Anúncios deste empreendimento
                  </h3>
                  <ul>{dados.anuncios.map(a => <LinhaAnuncio key={a.url_anuncio} a={a} />)}</ul>
                </section>
              </>
            ) : (
              <div className="text-sm text-mrv-text-muted space-y-2">
                <p className="text-mrv-text font-semibold">Nenhum anúncio confirmado para este empreendimento.</p>
                <p className="text-[12px]">
                  Procurado em {dados.total_historico ?? 0} anúncios já coletados na cidade. Tente:
                </p>
                <ul className="text-[12px] list-disc pl-5 space-y-1">
                  <li>informar o endereço <strong>com número</strong> — é o que localiza o prédio;</li>
                  <li>escrever o nome sem “Residencial”/“Condomínio” (ex.: “Reserva Arvoredo”);</li>
                  <li>coletar anúncios novos no bairro (botão abaixo).</li>
                </ul>
              </div>
            )}

            {dados.sugestoes && dados.sugestoes.length > 0 && (
              <section>
                <h3 className="text-[10px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] mb-2">
                  {g ? 'Outros prédios próximos do que foi digitado' : 'Prédios encontrados com o que foi digitado'}
                </h3>
                <ul className="space-y-1.5">
                  {dados.sugestoes.map(s => (
                    <li key={s.grupo_id}>
                      <button
                        type="button"
                        onClick={() => onAbrirGrupo(s)}
                        className="w-full text-left flex items-center justify-between gap-2 bg-mrv-surface-2/40 border border-mrv-border rounded-card px-3 py-2 hover:border-mrv-green transition-colors"
                      >
                        <span className="min-w-0">
                          <span className="block text-[12px] text-mrv-text font-semibold truncate">{tituloGrupo(s)}</span>
                          <span className="block text-[10px] text-mrv-text-dim">
                            {s.n_anuncios} anúncios · {s.area_min != null && `${Math.round(s.area_min)}–${Math.round(s.area_max ?? s.area_min)} m² · `}{s.bairro}
                          </span>
                        </span>
                        <span className="font-data font-bold text-[12px] text-mrv-text whitespace-nowrap">{formatarMoeda(s.preco_m2_mediana)}/m²</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {dados.provaveis.length > 0 && (
              <section>
                <button
                  type="button"
                  onClick={() => setVerProvaveis(v => !v)}
                  className="flex items-center gap-1 text-[10px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] hover:text-mrv-text"
                  aria-expanded={verProvaveis}
                >
                  <ChevronDown size={12} className={`transition-transform ${verProvaveis ? '' : '-rotate-90'}`} />
                  Talvez sejam deste empreendimento ({dados.provaveis.length})
                </button>
                {verProvaveis && (
                  <>
                    <p className="text-[10px] text-mrv-text-dim mt-1">
                      Fora das estatísticas: só a rua ou uma menção ao nome ligam estes anúncios ao que foi procurado.
                    </p>
                    <ul>{dados.provaveis.map(a => <LinhaAnuncio key={a.url_anuncio} a={a} />)}</ul>
                  </>
                )}
              </section>
            )}

            {procura && !coletar && (
              <button
                type="button"
                onClick={() => setColetar(true)}
                className="flex items-center gap-1.5 text-xs font-semibold text-mrv-orange border border-mrv-orange/40 px-3 py-2 rounded-card hover:bg-mrv-orange hover:text-white transition-colors"
                title="Roda uma busca normal nos portais, no bairro do empreendimento, e procura de novo"
              >
                <RefreshCw size={12} />
                Coletar anúncios novos no bairro e procurar de novo
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
