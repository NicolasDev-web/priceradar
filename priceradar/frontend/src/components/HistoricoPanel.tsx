import { ChevronRight, Clock, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { deletarHistorico, listarHistorico } from '../api/client'
import type { BuscaSalva } from '../types'

interface Props {
  cidade: string
  onReabrir: (busca: BuscaSalva) => void
  onFechar: () => void
}

function formatarData(iso: string): string {
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatarMoeda(v: number): string {
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 0 })
}

export function HistoricoPanel({ cidade, onReabrir, onFechar }: Props) {
  const [buscas, setBuscas] = useState<BuscaSalva[]>([])
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    listarHistorico(cidade)
      .then(r => setBuscas(r.buscas))
      .catch(() => setBuscas([]))
      .finally(() => setCarregando(false))
  }, [cidade])

  async function handleDeletar(id: string) {
    await deletarHistorico(id)
    setBuscas(prev => prev.filter(b => b.id !== id))
  }

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-sm bg-mrv-surface border-l border-mrv-border z-40 flex flex-col shadow-[−4px_0_32px_rgba(0,0,0,0.5)]">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-mrv-border">
        <div className="flex items-center gap-2 text-mrv-text">
          <Clock size={14} className="text-mrv-text-muted" />
          <h2 className="font-bold text-sm tracking-tight">Histórico de buscas</h2>
        </div>
        <button
          type="button"
          onClick={onFechar}
          className="text-mrv-text-dim hover:text-mrv-text transition-colors p-1 rounded hover:bg-mrv-surface-2"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {carregando ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-card p-4 bg-mrv-surface-2/60 border border-mrv-border animate-pulse">
              <div className="h-2.5 bg-mrv-border rounded w-2/3 mb-2" />
              <div className="h-3 bg-mrv-border/70 rounded w-1/2 mb-1.5" />
              <div className="h-2 bg-mrv-border/50 rounded w-1/3" />
            </div>
          ))
        ) : buscas.length === 0 ? (
          <div className="text-center py-16 text-mrv-text-muted">
            <Clock size={28} className="mx-auto mb-3 opacity-25" />
            <p className="text-sm">Nenhuma busca registrada.</p>
          </div>
        ) : (
          buscas.map(b => (
            <div
              key={b.id}
              className="rounded-card border border-mrv-border bg-mrv-base/60 p-4 hover:border-mrv-surface-2 hover:bg-mrv-surface-2/30 transition-all"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] text-mrv-text-dim mb-1 tracking-wide">{formatarData(b.criado_em)}</p>
                  <p className="text-sm font-semibold text-mrv-text truncate leading-snug">
                    {formatarMoeda(b.preco_min)} – {formatarMoeda(b.preco_max)}
                    {b.quartos ? ` · ${b.quartos}q` : ''}
                  </p>
                  <div className="flex items-center gap-3 mt-1.5 text-[11px] text-mrv-text-muted">
                    <span>{b.total_encontrado} resultados</span>
                    {b.preco_m2_medio > 0 && (
                      <span className="text-mrv-orange font-semibold font-data">
                        {formatarMoeda(b.preco_m2_medio)}/m²
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => onReabrir(b)}
                    className="text-mrv-text-muted hover:text-mrv-orange transition-colors"
                    title="Reabrir busca"
                  >
                    <ChevronRight size={15} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeletar(b.id)}
                    className="text-mrv-text-dim hover:text-red-400 transition-colors"
                    title="Excluir"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
