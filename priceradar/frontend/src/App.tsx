import axios from 'axios'
import { AlertTriangle, Clock, Download, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { buscarConcorrentes, exportarExcel } from './api/client'
import { ComparativoBairros } from './components/ComparativoBairros'
import { EmpreendimentoCard, NIVEL_INFO } from './components/EmpreendimentoCard'
import { EmpreendimentoPanel, type PedidoDossie } from './components/EmpreendimentoPanel'
import { EvolucaoBairrosChart } from './components/EvolucaoBairrosChart'
import { EvolucaoChart } from './components/EvolucaoChart'
import { FunilColeta } from './components/FunilColeta'
import { HistoricoPanel } from './components/HistoricoPanel'
import { KpiBar } from './components/KpiBar'
import { LoadingState } from './components/LoadingState'
import { Mapa } from './components/Mapa'
import { PriceChart } from './components/PriceChart'
import { ReferencialMRVForm } from './components/ReferencialMRVForm'
import { OrdenacaoControle } from './components/OrdenacaoControle'
import { ResultCard } from './components/ResultCard'
import { ResumoMudancas } from './components/ResumoMudancas'
import { SearchForm } from './components/SearchForm'
import { LABEL_PORTAL, PORTAL_CONFIG } from './data/portais'
import type { BuscaRequest, BuscaResponse, BuscaSalva, GrupoEmpreendimento, NivelGrupo, ProcurarEmpreendimentoRequest } from './types'
import { ordenar, type CriterioOrdem, type Direcao } from './utils/ordenacao'

// Abaixo disso a mediana oscila demais com um anúncio a mais ou a menos.
// Cidades do interior costumam cair aqui — o aviso evita que um número frágil
// seja levado para uma reunião como se fosse referência de mercado.
const MINIMO_AMOSTRA_CONFIAVEL = 15

export default function App() {
  const [loading, setLoading] = useState(false)
  const [exportando, setExportando] = useState(false)
  const [resultado, setResultado] = useState<BuscaResponse | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ultimaBusca, setUltimaBusca] = useState<BuscaRequest | null>(null)
  // Muda a cada busca bem-sucedida — usado como `key` do grid de resultados
  // para forçar remontagem e replay do stagger de entrada dos cards.
  const [buscaVersion, setBuscaVersion] = useState(0)
  // Ordem dos cards: lembrada entre sessões (conveniência; sem storage, volta ao padrão).
  const [criterio, setCriterio] = useState<CriterioOrdem>(() => {
    try { return (localStorage.getItem('priceradar_ordem') as CriterioOrdem) || 'preco_m2' } catch { return 'preco_m2' }
  })
  const [direcao, setDirecao] = useState<Direcao>(() => {
    try { return (localStorage.getItem('priceradar_direcao') as Direcao) || 'asc' } catch { return 'asc' }
  })
  useEffect(() => {
    try {
      localStorage.setItem('priceradar_ordem', criterio)
      localStorage.setItem('priceradar_direcao', direcao)
    } catch { /* storage indisponível: só não lembra */ }
  }, [criterio, direcao])
  const cardsOrdenados = useMemo(
    () => (resultado ? ordenar(resultado.empreendimentos, criterio, direcao) : []),
    [resultado, criterio, direcao],
  )
  // Cards por anúncio ou por empreendimento (prédio). Lembrada como a ordem.
  const [vista, setVista] = useState<'anuncios' | 'empreendimentos'>(() => {
    try { return localStorage.getItem('priceradar_vista') === 'empreendimentos' ? 'empreendimentos' : 'anuncios' } catch { return 'anuncios' }
  })
  useEffect(() => {
    try { localStorage.setItem('priceradar_vista', vista) } catch { /* só não lembra */ }
  }, [vista])
  const gruposPorId = useMemo(
    () => new Map((resultado?.grupos ?? []).map(g => [g.grupo_id, g])),
    [resultado],
  )
  // Aba de nível dentro da vista Empreendimentos: o exato mesmo prédio primeiro.
  const [abaNivel, setAbaNivel] = useState<NivelGrupo>('mesmo_predio')
  const contagemNivel = useMemo(() => {
    const c: Record<NivelGrupo, number> = { mesmo_predio: 0, mesmo_local: 0, mesmo_nome: 0 }
    for (const g of resultado?.grupos ?? []) c[g.nivel ?? 'mesmo_nome'] += 1
    return c
  }, [resultado])
  // A cada resultado, abre na aba mais forte que tem grupo — busca antiga do
  // cache (sem número de porta) não tem "Mesmo prédio" e abriria vazia.
  useEffect(() => {
    const primeira = (['mesmo_predio', 'mesmo_local', 'mesmo_nome'] as NivelGrupo[]).find(nv => contagemNivel[nv] > 0)
    setAbaNivel(primeira ?? 'mesmo_predio')
  }, [contagemNivel])
  const gruposOrdenados = useMemo(() => {
    const gs = (resultado?.grupos ?? []).filter(g => (g.nivel ?? 'mesmo_nome') === abaNivel)
    gs.sort((a, b) => (direcao === 'asc' ? 1 : -1) * (a.preco_m2_mediana - b.preco_m2_mediana))
    return gs
  }, [resultado, direcao, abaNivel])
  // Dossiê do empreendimento: aberto por um card/selo (grupo) ou pela procura
  // por nome/endereço. A cidade vai junto porque a procura pode vir antes de
  // qualquer busca.
  const [pedidoDossie, setPedidoDossie] = useState<PedidoDossie | null>(null)
  const [cidadeDossie, setCidadeDossie] = useState<string | null>(null)
  const [mostrarDossie, setMostrarDossie] = useState(false)
  const [mostrarHistorico, setMostrarHistorico] = useState(false)
  const [mostrarFormMRV, setMostrarFormMRV] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const buscaAbortRef = useRef<AbortController | null>(null)

  const fontesErro = resultado?.diagnostico?.fontes_erro ?? []
  const coletaFalhou = (resultado?.diagnostico?.fontes_ok.length ?? 0) === 0
  const coletaParcial = fontesErro.length > 0 && !coletaFalhou

  async function handleBuscar(params: BuscaRequest, forcar = false) {
    // Reenviar o formulário (ou clicar "Atualizar" de novo) enquanto a busca
    // anterior ainda está em voo cancela a antiga — sem isso, a que responder
    // por último decide a tela, mesmo que seja a mais velha.
    buscaAbortRef.current?.abort()
    const controller = new AbortController()
    buscaAbortRef.current = controller

    const idDoJob = crypto.randomUUID()
    setJobId(idDoJob)
    setLoading(true)
    setErro(null)
    setResultado(null)
    setUltimaBusca(params)
    try {
      const dados = await buscarConcorrentes(params, forcar, { jobId: idDoJob, signal: controller.signal })
      setResultado(dados)
      setBuscaVersion(v => v + 1)
    } catch (e: unknown) {
      if (axios.isCancel(e)) return // busca cancelada por um reenvio — não é erro

      // 422 = a API recusou os filtros (ex.: cidade sem UF). Mostrar o motivo
      // real, não "verifique se o servidor está rodando" — que manda o usuário
      // investigar a coisa errada.
      const resp = (e as { response?: { status?: number; data?: { detail?: unknown } } }).response
      const detalhe = resp?.data?.detail
      if (resp?.status === 422 && Array.isArray(detalhe)) {
        const motivos = detalhe
          .map((d: { msg?: string }) => (d.msg ?? '').replace(/^Value error,\s*/, ''))
          .filter(Boolean)
        setErro(motivos.join('\n') || 'Filtros inválidos.')
      } else {
        const msg = e instanceof Error ? e.message : 'Erro desconhecido'
        setErro(`Não foi possível buscar os dados. Verifique se o servidor está rodando.\n${msg}`)
      }
    } finally {
      // Só limpa o estado se esta ainda for a busca vigente — a que acabou
      // de ser cancelada por um reenvio não pode apagar o loading/jobId da
      // busca nova que já está rodando.
      if (buscaAbortRef.current === controller) {
        setLoading(false)
        setJobId(null)
      }
    }
  }

  function handleAtualizar() {
    if (ultimaBusca) handleBuscar(ultimaBusca, true)
  }

  async function handleExportar() {
    if (!ultimaBusca || !resultado) return
    setExportando(true)
    try {
      await exportarExcel(ultimaBusca, resultado)
    } catch {
      setErro('Erro ao exportar Excel.')
    } finally {
      setExportando(false)
    }
  }

  function handleReabrirHistorico(busca: BuscaSalva) {
    setMostrarHistorico(false)
    // Todos os filtros que mudam o resultado: sem bairros/banheiros/tipo, a
    // busca reaberta era outra busca e nunca casava com o cache.
    handleBuscar({
      cidade: busca.cidade,
      preco_min: busca.preco_min,
      preco_max: busca.preco_max,
      quartos: busca.quartos,
      bairros: busca.bairros ?? null,
      banheiros: busca.banheiros ?? null,
      tipo_edificacao: busca.tipo_edificacao ?? null,
    })
  }

  function abrirGrupo(grupo: GrupoEmpreendimento, cidade?: string) {
    const alvo = cidade ?? ultimaBusca?.cidade ?? cidadeDossie
    if (!alvo) return
    setCidadeDossie(alvo)
    setPedidoDossie({ tipo: 'grupo', grupoId: grupo.grupo_id, titulo: grupo.nome ?? grupo.endereco ?? undefined })
    setMostrarDossie(true)
  }

  function handleProcurarEmpreendimento(params: ProcurarEmpreendimentoRequest) {
    setCidadeDossie(params.cidade)
    setPedidoDossie({ tipo: 'procura', params })
    setMostrarDossie(true)
  }

  async function handleMRVSalvo() {
    setMostrarFormMRV(false)
    if (ultimaBusca) {
      await handleBuscar(ultimaBusca)
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-mrv-base font-sans">

      {/* Header */}
      <header className="bg-mrv-surface border-b border-mrv-border">
        <div className="max-w-7xl mx-auto px-4 md:px-6 py-3.5 flex items-center justify-between">

          {/* Logo + nome */}
          <div className="flex items-center gap-3">
            {/* Sigla MRV estilizada */}
            <div className="flex items-center gap-px">
              <div className="w-2.5 h-[18px] bg-mrv-orange rounded-[2px]" />
              <div className="w-2.5 h-[18px] bg-mrv-text rounded-[2px]" />
              <div className="w-2.5 h-[18px] bg-mrv-orange rounded-[2px]" />
            </div>
            <div className="w-px h-7 bg-mrv-border mx-1" />
            <div>
              <h1 className="font-bold text-[17px] leading-none tracking-tight text-mrv-text">
                Price<span className="text-mrv-orange">Radar</span>
              </h1>
              <p className="text-[10px] text-mrv-text-muted leading-none mt-0.5 tracking-widest uppercase">
                Inteligência Competitiva
              </p>
            </div>
          </div>

          {/* Ações */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMostrarHistorico(true)}
              className="flex items-center gap-1.5 text-xs font-medium text-mrv-text-muted hover:text-mrv-text px-3 py-2 rounded-card hover:bg-mrv-surface-2 transition-colors"
            >
              <Clock size={14} />
              <span className="hidden sm:inline tracking-wide">Histórico</span>
            </button>

            {resultado && resultado.total > 0 && (
              <button
                type="button"
                onClick={handleExportar}
                disabled={exportando}
                className="flex items-center gap-1.5 text-xs font-semibold bg-mrv-orange hover:bg-mrv-orange-dark disabled:opacity-40 text-white px-4 py-2 rounded-card transition-colors"
              >
                <Download size={13} />
                <span className="hidden sm:inline">{exportando ? 'Exportando...' : 'Exportar Excel'}</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 md:px-6 py-6">

        <SearchForm onBuscar={handleBuscar} onProcurarEmpreendimento={handleProcurarEmpreendimento} loading={loading} />

        {erro && (
          <div className="bg-red-950/60 border border-red-800/50 text-red-300 rounded-card px-5 py-4 text-sm whitespace-pre-line mb-6 motion-safe:animate-fade-up">
            <strong className="text-red-200">Erro:</strong> {erro}
          </div>
        )}

        {loading && <LoadingState jobId={jobId} />}

        {resultado && !loading && (
          <>
            {resultado.total === 0 ? (
              /* Estado vazio. Distingue falha de coleta de ausência real de
                 mercado: apresentar uma falha técnica como "não há imóveis"
                 leva o time a conclusões erradas sobre o recorte. */
              coletaFalhou ? (
                <div className="bg-mrv-surface border border-red-800/50 rounded-panel p-12 text-center">
                  <AlertTriangle size={36} className="mx-auto text-red-400 mb-4" />
                  <p className="text-mrv-text font-semibold text-base mb-1">
                    Falha na coleta — resultado não confiável
                  </p>
                  <p className="text-mrv-text-muted text-sm mb-5 max-w-md mx-auto leading-relaxed">
                    Nenhuma fonte respondeu. Isto <strong className="text-mrv-text">não</strong> significa
                    que não existem imóveis nesse recorte — significa que não conseguimos consultar os portais.
                  </p>
                  <div className="inline-block text-left bg-mrv-surface-2/50 border border-mrv-border rounded-card px-5 py-4">
                    <p className="text-mrv-text-muted text-xs font-semibold uppercase tracking-wider mb-2">Fontes com erro</p>
                    <p className="text-red-300 text-sm">{fontesErro.map(LABEL_PORTAL).join(' · ') || '—'}</p>
                  </div>
                  <div className="mt-5">
                    <button
                      type="button"
                      onClick={handleAtualizar}
                      className="flex items-center gap-1.5 mx-auto text-xs font-semibold text-mrv-orange border border-mrv-orange/40 px-4 py-2 rounded-card hover:bg-mrv-orange hover:text-white transition-colors"
                    >
                      <RefreshCw size={13} />
                      Tentar novamente
                    </button>
                  </div>
                </div>
              ) : (
              <div className="bg-mrv-surface border border-mrv-border rounded-panel p-16 text-center">
                {/* Ícone de radar estático */}
                <div className="relative w-20 h-20 mx-auto mb-6">
                  <div className="absolute inset-0 rounded-full border-2 border-mrv-border" />
                  <div className="absolute inset-3 rounded-full border border-mrv-border/60" />
                  <div className="absolute inset-6 rounded-full border border-mrv-border/40" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-1.5 h-1.5 rounded-full bg-mrv-text-dim" />
                  </div>
                  {/* Linha de varredura */}
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-px h-1/2 bg-gradient-to-b from-mrv-text-dim to-transparent origin-bottom" style={{ transform: 'rotate(-45deg)', transformOrigin: 'bottom center' }} />
                  </div>
                </div>
                <p className="text-mrv-text font-semibold text-base mb-1">Nenhum resultado no radar</p>
                <p className="text-mrv-text-muted text-sm mb-5">
                  Não encontramos empreendimentos com esses filtros.
                </p>
                <div className="inline-flex flex-col gap-2 text-left bg-mrv-surface-2/50 border border-mrv-border rounded-card px-5 py-4">
                  <p className="text-mrv-text-muted text-xs font-semibold uppercase tracking-wider mb-1">Sugestões</p>
                  <p className="text-mrv-text-muted text-sm">· Amplie a faixa de preço (±20%)</p>
                  <p className="text-mrv-text-muted text-sm">· Remova o filtro de tipologia</p>
                  <p className="text-mrv-text-muted text-sm">· Verifique a grafia da cidade</p>
                </div>
              </div>
              )
            ) : (
              <>
                {resultado.do_cache && (
                  <div className="flex items-center justify-between gap-3 bg-mrv-surface border border-mrv-border rounded-card px-4 py-3 mb-4 motion-safe:animate-fade-up">
                    <p className="text-sm text-mrv-text-muted">
                      <span className="font-semibold text-mrv-orange">Cache ativo.</span>{' '}
                      Dados coletados recentemente. Atualize para nova varredura.
                    </p>
                    <button
                      type="button"
                      onClick={handleAtualizar}
                      disabled={loading}
                      className="flex items-center gap-1.5 text-xs font-semibold text-mrv-orange border border-mrv-orange/40 px-3 py-1.5 rounded-card hover:bg-mrv-orange hover:text-white transition-colors whitespace-nowrap disabled:opacity-40"
                    >
                      <RefreshCw size={13} />
                      Atualizar
                    </button>
                  </div>
                )}

                {/* Coleta parcial: há resultado, mas alguma fonte falhou.
                    O número é utilizável, só que sobre uma amostra menor. */}
                {coletaParcial && (
                  <div className="flex items-start gap-2.5 bg-amber-950/40 border border-amber-800/40 rounded-card px-4 py-3 mb-4 motion-safe:animate-fade-up">
                    <AlertTriangle size={15} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-amber-200/90 leading-relaxed">
                      <span className="font-semibold">Coleta parcial.</span>{' '}
                      Não foi possível consultar {fontesErro.map(LABEL_PORTAL).join(', ')}.
                      Os números refletem apenas as fontes que responderam
                      ({resultado.diagnostico?.fontes_ok.map(LABEL_PORTAL).join(', ')}).
                    </p>
                  </div>
                )}

                {/* Amostra pequena: em cidades do interior os portais têm pouco
                    estoque. A mediana de 5 anúncios não sustenta uma decisão de
                    preço, e o número sozinho não deixa isso evidente. */}
                {resultado.total < MINIMO_AMOSTRA_CONFIAVEL && (
                  <div className="flex items-start gap-2.5 bg-amber-950/40 border border-amber-800/40 rounded-card px-4 py-3 mb-4 motion-safe:animate-fade-up">
                    <AlertTriangle size={15} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-amber-200/90 leading-relaxed">
                      <span className="font-semibold">Amostra pequena ({resultado.total} anúncios).</span>{' '}
                      Use como indicativo, não como referência de preço. Amplie a faixa
                      de preço ou remova o filtro de tipologia para uma base maior.
                    </p>
                  </div>
                )}

                {resultado.comparacao && <ResumoMudancas comparacao={resultado.comparacao} />}

                {resultado.diagnostico && !resultado.do_cache && (
                  <FunilColeta diagnostico={resultado.diagnostico} exibidos={resultado.total} />
                )}

                <KpiBar dados={resultado} onEditarMRV={() => setMostrarFormMRV(true)} />

                <ComparativoBairros
                  dados={resultado.por_bairro ?? []}
                  minimoConfiavel={MINIMO_AMOSTRA_CONFIAVEL}
                />

                {/* Mesma pergunta do comparativo — "onde?" — em forma espacial.
                    Evolução (tempo) e distribuição vêm depois. */}
                <Mapa
                  empreendimentos={resultado.empreendimentos}
                  precoM2Medio={resultado.preco_m2_medio}
                  semLocalizacao={resultado.sem_localizacao ?? 0}
                  comCoordenada={resultado.diagnostico?.com_coordenada}
                />

                {/* Gráfico de evolução histórica */}
                {ultimaBusca && (
                  <EvolucaoChart cidade={ultimaBusca.cidade} quartos={ultimaBusca.quartos} />
                )}

                {/* Mesma evolução aberta por bairro. Padrão: os bairros da busca;
                    busca sem bairro → os de maior volume no histórico. */}
                {ultimaBusca && (
                  <EvolucaoBairrosChart
                    cidade={ultimaBusca.cidade}
                    quartos={ultimaBusca.quartos}
                    bairros={ultimaBusca.bairros ?? (ultimaBusca.bairro ? [ultimaBusca.bairro] : null)}
                  />
                )}

                <PriceChart dados={resultado} />

                {/* Cabeçalho da lista de resultados com badges de portais */}
                <div className="mb-3 mt-6 flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-3 flex-wrap">
                    {/* Anúncio ≠ empreendimento: um prédio pode ter vários anúncios. */}
                    <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em]">
                      {resultado.total} anúncio{resultado.total !== 1 ? 's' : ''}
                      {' · '}{contagemNivel.mesmo_predio} prédio{contagemNivel.mesmo_predio !== 1 ? 's' : ''} com 2+ anúncios
                    </h2>
                    <div role="tablist" aria-label="Ver por" className="flex border border-mrv-border rounded-card overflow-hidden text-[11px]">
                      {(['anuncios', 'empreendimentos'] as const).map(v => (
                        <button
                          key={v}
                          type="button"
                          role="tab"
                          aria-selected={vista === v}
                          onClick={() => setVista(v)}
                          className={`px-2.5 py-1 font-semibold transition-colors ${vista === v
                            ? 'bg-mrv-green text-white'
                            : 'text-mrv-text-muted hover:text-mrv-text'}`}
                        >
                          {v === 'anuncios' ? 'Anúncios' : 'Empreendimentos'}
                        </button>
                      ))}
                    </div>
                  </div>
                  <OrdenacaoControle
                    criterio={criterio}
                    direcao={direcao}
                    onCriterio={setCriterio}
                    onDirecao={setDirecao}
                  />
                  <div className="flex gap-1.5 flex-wrap w-full">
                    {Object.entries(PORTAL_CONFIG).map(([portalKey, cfg]) => {
                      const count = resultado.empreendimentos.filter(e => e.portal === portalKey).length
                      if (!count) return null
                      return (
                        <span
                          key={portalKey}
                          className={`text-[10px] font-semibold px-2.5 py-1 rounded-full tracking-wide ${cfg.color}`}
                        >
                          {cfg.label} <span className="opacity-70">({count})</span>
                        </span>
                      )
                    })}
                  </div>
                </div>

                {vista === 'empreendimentos' ? (
                  <>
                    {/* Uma aba por nível de prova: quem lê escolhe o quanto quer
                        de certeza, em vez de um grupo só que mistura prova e palpite. */}
                    <div role="tablist" aria-label="Tipo de agrupamento" className="flex flex-wrap gap-1.5 mt-1 mb-2">
                      {(Object.keys(NIVEL_INFO) as NivelGrupo[]).map(nv => (
                        <button
                          key={nv}
                          type="button"
                          role="tab"
                          aria-selected={abaNivel === nv}
                          onClick={() => setAbaNivel(nv)}
                          className={`text-[11px] font-semibold px-3 py-1.5 rounded-card border transition-colors ${abaNivel === nv
                            ? 'bg-mrv-green text-white border-mrv-green'
                            : 'text-mrv-text-muted border-mrv-border hover:text-mrv-text'}`}
                        >
                          {NIVEL_INFO[nv].rotulo} ({contagemNivel[nv]})
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-mrv-text-dim mb-2">
                      {NIVEL_INFO[abaNivel].explicacao}
                      {abaNivel === 'mesmo_predio' && (
                        <> Só VivaReal, ZAP e ChavesNaMão publicam o número — anúncios da OLX não entram nesta aba
                        (aparecem em “Mesmo nome”). Anúncio sem número no mesmo ponto aparece como “provável”, fora do preço.</>
                      )}
                    </p>
                    {gruposOrdenados.length === 0 ? (
                      <p className="text-sm text-mrv-text-muted bg-mrv-surface border border-mrv-border rounded-card px-4 py-6 text-center">
                        Nenhum grupo deste tipo nesta busca. Use “Procurar empreendimento” para buscar no histórico.
                      </p>
                    ) : (
                      <div key={`g${buscaVersion}`} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {gruposOrdenados.map((g, i) => (
                          <EmpreendimentoCard
                            key={g.grupo_id}
                            grupo={g}
                            precoM2Medio={resultado.preco_m2_medio}
                            onAbrir={grupo => abrirGrupo(grupo)}
                            indice={i}
                          />
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div key={buscaVersion} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
                    {cardsOrdenados.map((emp, i) => (
                      <ResultCard
                        key={emp.id}
                        empreendimento={emp}
                        precoM2Medio={resultado.preco_m2_medio}
                        indice={i}
                        grupo={emp.grupo_id ? gruposPorId.get(emp.grupo_id) : undefined}
                        onAbrirGrupo={grupo => abrirGrupo(grupo)}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Estado inicial — sem busca ainda */}
        {!resultado && !loading && !erro && (
          <div className="text-center py-28">
            {/* Radar animado */}
            <div className="relative w-24 h-24 mx-auto mb-7">
              <div className="absolute inset-0 rounded-full border border-mrv-border" />
              <div className="absolute inset-4 rounded-full border border-mrv-border/60" />
              <div className="absolute inset-8 rounded-full border border-mrv-border/40" />
              {/* Ponto central */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-mrv-orange shadow-[0_0_8px_2px_rgba(243,146,0,0.4)]" />
              </div>
              {/* Varredura rotativa */}
              <div className="absolute inset-0 rounded-full overflow-hidden motion-safe:animate-radar-spin">
                <div
                  className="absolute bottom-1/2 left-1/2 w-px origin-bottom"
                  style={{
                    height: 'calc(50% - 2px)',
                    background: 'linear-gradient(to top, rgba(11,90,66,0.8), transparent)',
                    transform: 'translateX(-50%)',
                  }}
                />
              </div>
              {/* Setor iluminado */}
              <div
                className="absolute inset-0 rounded-full motion-safe:animate-radar-spin"
                style={{
                  background: 'conic-gradient(from 0deg, rgba(11,90,66,0.15) 0deg, transparent 60deg)',
                }}
              />
            </div>
            <p className="text-mrv-text font-semibold text-base tracking-tight">
              Radar aguardando busca
            </p>
            <p className="text-mrv-text-muted text-sm mt-1.5 max-w-xs mx-auto leading-relaxed">
              Configure os filtros acima e inicie a varredura de mercado
            </p>
          </div>
        )}
      </main>

      <footer className="text-center text-[10px] text-mrv-text-dim tracking-widest uppercase py-5 border-t border-mrv-border bg-mrv-surface">
        PriceRadar v2.0 · MRV Engenharia
      </footer>

      {/* Modais / Painéis. Ficam montados sempre que há uma cidade de
          referência — quem decide aberto/fechado é `isOpen`, para a
          animação de saída poder tocar antes do componente sumir do DOM. */}
      {ultimaBusca && (
        <HistoricoPanel
          isOpen={mostrarHistorico}
          cidade={ultimaBusca.cidade}
          onReabrir={handleReabrirHistorico}
          onFechar={() => setMostrarHistorico(false)}
        />
      )}

      {cidadeDossie && (
        <EmpreendimentoPanel
          isOpen={mostrarDossie}
          cidade={cidadeDossie}
          pedido={pedidoDossie}
          precoM2Referencia={resultado && ultimaBusca?.cidade === cidadeDossie ? resultado.preco_m2_mediana : null}
          onAbrirGrupo={grupo => abrirGrupo(grupo, cidadeDossie)}
          onFechar={() => setMostrarDossie(false)}
        />
      )}

      {ultimaBusca && (
        <ReferencialMRVForm
          isOpen={mostrarFormMRV}
          cidade={ultimaBusca.cidade}
          quartos={ultimaBusca.quartos}
          onSalvo={handleMRVSalvo}
          onFechar={() => setMostrarFormMRV(false)}
        />
      )}
    </div>
  )
}
