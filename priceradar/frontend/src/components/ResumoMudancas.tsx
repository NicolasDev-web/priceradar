/**
 * "Desde a última busca igual (12/09): 8 novos · 3 baixaram de preço ·
 * 1 subiu · 2 saíram do ar". Só aparece quando existe busca anterior igual.
 */
import { History } from 'lucide-react'
import type { ComparacaoBusca } from '../types'

export function ResumoMudancas({ comparacao }: { comparacao: ComparacaoBusca }) {
  const { novos, baixaram, subiram, sairam } = comparacao
  const d = new Date(comparacao.data_anterior)
  const data = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
  const partes: [number, string, string][] = [
    [novos, novos === 1 ? 'novo' : 'novos', 'text-sky-300'],
    [baixaram, baixaram === 1 ? 'baixou de preço' : 'baixaram de preço', 'text-emerald-300'],
    [subiram, subiram === 1 ? 'subiu de preço' : 'subiram de preço', 'text-orange-300'],
    [sairam, sairam === 1 ? 'saiu do ar' : 'saíram do ar', 'text-mrv-text-muted'],
  ]
  const comMudanca = partes.filter(([n]) => n > 0)

  return (
    <div className="flex items-center gap-2 flex-wrap bg-mrv-surface border border-mrv-border rounded-card px-4 py-2.5 mb-4 text-[12px] text-mrv-text-muted">
      <History size={13} className="text-mrv-text-dim" />
      <span>Desde a última busca igual ({data}):</span>
      {comMudanca.length === 0 ? (
        <span className="text-mrv-text">nada mudou.</span>
      ) : (
        comMudanca.map(([n, rotulo, cor], i) => (
          <span key={rotulo}>
            {i > 0 && <span className="text-mrv-text-dim mr-2">·</span>}
            <span className={`font-data font-semibold ${cor}`}>{n}</span> {rotulo}
          </span>
        ))
      )}
    </div>
  )
}
