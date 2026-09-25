import { ArrowDownWideNarrow, ArrowUpNarrowWide } from 'lucide-react'
import { CRITERIOS, type CriterioOrdem, type Direcao } from '../utils/ordenacao'

interface Props {
  criterio: CriterioOrdem
  direcao: Direcao
  onCriterio: (c: CriterioOrdem) => void
  onDirecao: (d: Direcao) => void
}

export function OrdenacaoControle({ criterio, direcao, onCriterio, onDirecao }: Props) {
  const atual = CRITERIOS.find(c => c.valor === criterio) ?? CRITERIOS[0]
  const Icone = direcao === 'asc' ? ArrowUpNarrowWide : ArrowDownWideNarrow
  return (
    <div className="flex items-center gap-2 text-[11px] text-mrv-text-muted">
      <label htmlFor="ordenar-por" className="uppercase tracking-[0.1em] text-mrv-text-dim font-semibold">
        Ordenar
      </label>
      <select
        id="ordenar-por"
        value={criterio}
        onChange={e => onCriterio(e.target.value as CriterioOrdem)}
        className="bg-mrv-surface border border-mrv-border rounded-card px-2 py-1 text-mrv-text focus:outline-none focus:border-mrv-green"
      >
        {CRITERIOS.map(c => (
          <option key={c.valor} value={c.valor}>{c.rotulo}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => onDirecao(direcao === 'asc' ? 'desc' : 'asc')}
        className="flex items-center gap-1 border border-mrv-border rounded-card px-2 py-1 hover:border-mrv-green hover:text-mrv-text transition-colors"
        title="Inverter a ordem"
        aria-label={`Inverter a ordem (agora: ${direcao === 'asc' ? atual.asc : atual.desc})`}
      >
        <Icone size={13} />
        {direcao === 'asc' ? atual.asc : atual.desc}
      </button>
    </div>
  )
}
