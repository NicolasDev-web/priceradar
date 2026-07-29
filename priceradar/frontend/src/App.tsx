import { AlertTriangle, Clock, Download, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { buscarConcorrentes, exportarExcel } from './api/client'
import { EvolucaoChart } from './components/EvolucaoChart'
import { HistoricoPanel } from './components/HistoricoPanel'
import { KpiBar } from './components/KpiBar'
import { LoadingState } from './components/LoadingState'
import { PriceChart } from './components/PriceChart'
import { ReferencialMRVForm } from './components/ReferencialMRVForm'
import { ResultCard } from './components/ResultCard'
import { SearchForm } from './components/SearchForm'
import type { BuscaRequest, BuscaResponse, BuscaSalva } from './types'

// Configuração de todos os portais suportados
const PORTAL_CONFIG: Record<string, { label: string; color: string }> = {
  vivareal:     { label: 'VivaReal',     color: 'bg-emerald-900/60 text-emerald-300 border border-emerald-700/40' },
  zapimoveis:   { label: 'ZAP',          color: 'bg-amber-900/60 text-amber-300 border border-amber-700/40' },
  chavesnamao:  { label: 'ChavesNaMão',  color: 'bg-rose-900/60 text-rose-300 border border-rose-700/40' },
  imovelweb:    { label: 'ImovelWeb',    color: 'bg-sky-900/60 text-sky-300 border border-sky-700/40' },
  olx:          { label: 'OLX',          color: 'bg-indigo-900/60 text-indigo-300 border border-indigo-700/40' },
  quintoandar:  { label: 'QuintoAndar',  color: 'bg-teal-900/60 text-teal-300 border border-teal-700/40' },
  netimoveis:   { label: 'NetImóveis',   color: 'bg-violet-900/60 text-violet-300 border border-violet-700/40' },
  mercadolivre: { label: 'Mercado Livre',color: 'bg-yellow-900/60 text-yellow-300 border border-yellow-700/40' },
}

const LABEL_PORTAL = (p: string) => PORTAL_CONFIG[p]?.label ?? p

export default function App() {
  const [loading, setLoading] = useState(false)
  const [exportando, setExportando] = useState(false)
  const [resultado, setResultado] = useState<BuscaResponse | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ultimaBusca, setUltimaBusca] = useState<BuscaRequest | null>(null)
  const [mostrarHistorico, setMostrarHistorico] = useState(false)
  const [mostrarFormMRV, setMostrarFormMRV] = useState(false)

  const fontesErro = resultado?.diagnostico?.fontes_erro ?? []
  const coletaFalhou = (resultado?.diagnostico?.fontes_ok.length ?? 0) === 0
  const coletaParcial = fontesErro.length > 0 && !coletaFalhou

  async function handleBuscar(params: BuscaRequest, forcar = false) {
    setLoading(true)
    setErro(null)
    setResultado(null)
    setUltimaBusca(params)
    try {
      const dados = await buscarConcorrentes(params, forcar)
      setResultado(dados)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Erro desconhecido'
      setErro(`Não foi possível buscar os dados. Verifique se o servidor está rodando.\n${msg}`)
    } finally {
      setLoading(false)
    }
  }

  function handleAtualizar() {
    if (ultimaBusca) handleBuscar(ultimaBusca, true)
  }

  async function handleExportar() {
    if (!ultimaBusca || !resultado) return
    setExportando(true)
    try {
      await exportarExcel(ultimaBusca.cidade, resultado)
    } catch {
      setErro('Erro ao exportar Excel.')
    } finally {
      setExportando(false)
    }
  }

  function handleReabrirHistorico(busca: BuscaSalva) {
    setMostrarHistorico(false)
    handleBuscar({
      cidade: busca.cidade,
      preco_min: busca.preco_min,
      preco_max: busca.preco_max,
      quartos: busca.quartos,
    })
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

        <SearchForm onBuscar={handleBuscar} loading={loading} />

        {erro && (
          <div className="bg-red-950/60 border border-red-800/50 text-red-300 rounded-card px-5 py-4 text-sm whitespace-pre-line mb-6">
            <strong className="text-red-200">Erro:</strong> {erro}
          </div>
        )}

        {loading && <LoadingState />}

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
                  <div className="flex items-center justify-between gap-3 bg-mrv-surface border border-mrv-border rounded-card px-4 py-3 mb-4">
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
                  <div className="flex items-start gap-2.5 bg-amber-950/40 border border-amber-800/40 rounded-card px-4 py-3 mb-4">
                    <AlertTriangle size={15} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-amber-200/90 leading-relaxed">
                      <span className="font-semibold">Coleta parcial.</span>{' '}
                      Não foi possível consultar {fontesErro.map(LABEL_PORTAL).join(', ')}.
                      Os números refletem apenas as fontes que responderam
                      ({resultado.diagnostico?.fontes_ok.map(LABEL_PORTAL).join(', ')}).
                    </p>
                  </div>
                )}

                <KpiBar dados={resultado} onEditarMRV={() => setMostrarFormMRV(true)} />

                {/* Gráfico de evolução histórica */}
                {ultimaBusca && (
                  <EvolucaoChart cidade={ultimaBusca.cidade} quartos={ultimaBusca.quartos} />
                )}

                <PriceChart dados={resultado} />

                {/* Cabeçalho da lista de resultados com badges de portais */}
                <div className="mb-3 mt-6 flex items-center justify-between gap-3 flex-wrap">
                  <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em]">
                    {resultado.total} empreendimento{resultado.total !== 1 ? 's' : ''} encontrado{resultado.total !== 1 ? 's' : ''}
                  </h2>
                  <div className="flex gap-1.5 flex-wrap">
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

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
                  {resultado.empreendimentos.map(emp => (
                    <ResultCard
                      key={emp.id}
                      empreendimento={emp}
                      precoM2Medio={resultado.preco_m2_medio}
                    />
                  ))}
                </div>
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
              <div
                className="absolute inset-0 rounded-full overflow-hidden"
                style={{ animation: 'spin 3s linear infinite' }}
              >
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
                className="absolute inset-0 rounded-full"
                style={{
                  background: 'conic-gradient(from 0deg, rgba(11,90,66,0.15) 0deg, transparent 60deg)',
                  animation: 'spin 3s linear infinite',
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

      {/* Modais / Painéis */}
      {mostrarHistorico && ultimaBusca && (
        <HistoricoPanel
          cidade={ultimaBusca.cidade}
          onReabrir={handleReabrirHistorico}
          onFechar={() => setMostrarHistorico(false)}
        />
      )}

      {mostrarFormMRV && ultimaBusca && (
        <ReferencialMRVForm
          cidade={ultimaBusca.cidade}
          quartos={ultimaBusca.quartos}
          onSalvo={handleMRVSalvo}
          onFechar={() => setMostrarFormMRV(false)}
        />
      )}
    </div>
  )
}
