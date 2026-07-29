import { X } from 'lucide-react'
import { useState } from 'react'
import { cadastrarReferencialMRV } from '../api/client'

interface Props {
  cidade: string
  quartos: number | null
  onSalvo: () => void
  onFechar: () => void
}

function formatarMilhar(valor: string): string {
  const nums = valor.replace(/\D/g, '')
  return nums.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

export function ReferencialMRVForm({ cidade, quartos, onSalvo, onFechar }: Props) {
  const [produto, setProduto] = useState('')
  const [precoM2, setPrecoM2] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErro(null)
    const preco = parseFloat(precoM2.replace(/\./g, '').replace(',', '.'))
    if (!preco || preco <= 0) { setErro('Informe um preço/m² válido.'); return }
    setSalvando(true)
    try {
      await cadastrarReferencialMRV({ cidade, produto, preco_m2: preco, quartos })
      onSalvo()
    } catch {
      setErro('Erro ao salvar. Tente novamente.')
    } finally {
      setSalvando(false)
    }
  }

  const inputCls =
    'w-full bg-mrv-base border border-mrv-border rounded-card px-4 py-2.5 text-sm text-mrv-text placeholder-mrv-text-dim ' +
    'focus:outline-none focus:border-mrv-green focus:ring-1 focus:ring-mrv-green/30 transition-all'

  const labelCls = 'block text-[10px] font-semibold text-mrv-text-dim mb-1.5 uppercase tracking-[0.1em]'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-mrv-surface border border-mrv-border rounded-panel w-full max-w-md shadow-card-hover">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-mrv-border">
          <div>
            <h2 className="font-bold text-mrv-text text-sm tracking-tight">Referencial MRV</h2>
            <p className="text-[10px] text-mrv-text-muted mt-0.5 tracking-wide">
              {cidade}{quartos ? ` · ${quartos} quartos` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onFechar}
            className="text-mrv-text-dim hover:text-mrv-text transition-colors p-1 rounded hover:bg-mrv-surface-2"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className={labelCls}>Nome do produto MRV</label>
            <input
              type="text"
              value={produto}
              onChange={e => setProduto(e.target.value)}
              placeholder="Ex: MRV Parque Atlântico"
              required
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>Preço/m² de referência</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mrv-text-dim text-xs font-semibold select-none">R$</span>
              <input
                type="text"
                value={precoM2}
                onChange={e => setPrecoM2(formatarMilhar(e.target.value))}
                placeholder="5.500"
                required
                className={`${inputCls} pl-9`}
              />
            </div>
          </div>

          {erro && (
            <p className="text-xs text-red-400 bg-red-950/60 border border-red-800/40 px-3 py-2 rounded-card">
              {erro}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onFechar}
              className="flex-1 border border-mrv-border text-mrv-text-muted font-semibold px-4 py-2.5 rounded-card text-sm hover:bg-mrv-surface-2 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={salvando}
              className="flex-1 bg-mrv-orange hover:bg-mrv-orange-dark disabled:opacity-40 text-white font-semibold px-4 py-2.5 rounded-card text-sm transition-colors"
            >
              {salvando ? 'Salvando...' : 'Salvar referencial'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
