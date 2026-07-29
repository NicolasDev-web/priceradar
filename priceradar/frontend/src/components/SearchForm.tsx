import { Search } from 'lucide-react'
import { useState } from 'react'
import type { BuscaRequest } from '../types'

interface Props {
  onBuscar: (params: BuscaRequest) => void
  loading: boolean
}

function formatarMilhar(valor: string): string {
  const nums = valor.replace(/\D/g, '')
  return nums.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

const inputBase =
  'w-full bg-mrv-base border border-mrv-border rounded-card px-4 py-2.5 text-sm text-mrv-text placeholder-mrv-text-dim ' +
  'focus:outline-none focus:border-mrv-green focus:ring-1 focus:ring-mrv-green/30 transition-all ' +
  'font-sans'

const labelBase =
  'block text-[10px] font-semibold text-mrv-text-dim mb-1.5 uppercase tracking-[0.1em]'

export function SearchForm({ onBuscar, loading }: Props) {
  const [cidade, setCidade] = useState('Fortaleza, CE')
  const [bairro, setBairro] = useState('')
  const [precoMin, setPrecoMin] = useState('280.000')
  const [precoMax, setPrecoMax] = useState('500.000')
  const [quartos, setQuartos] = useState<string>('')

  function parseMoeda(s: string): number {
    return parseFloat(s.replace(/\./g, '').replace(',', '.')) || 0
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onBuscar({
      cidade,
      preco_min: parseMoeda(precoMin),
      preco_max: parseMoeda(precoMax),
      quartos: quartos ? parseInt(quartos) : null,
      bairro: bairro.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="bg-mrv-surface border border-mrv-border rounded-panel p-5 mb-5">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4 items-end">

        {/* Cidade */}
        <div className="lg:col-span-2">
          <label className={labelBase}>Cidade</label>
          <input
            type="text"
            value={cidade}
            onChange={e => setCidade(e.target.value)}
            placeholder="Ex: Salvador, BA"
            required
            className={inputBase}
          />
        </div>

        {/* Bairro */}
        <div>
          <label className={labelBase}>
            Bairro{' '}
            <span className="normal-case text-mrv-text-dim font-normal">(opc.)</span>
          </label>
          <input
            type="text"
            value={bairro}
            onChange={e => setBairro(e.target.value)}
            placeholder="Ex: Meireles"
            className={inputBase}
          />
        </div>

        {/* Preço mínimo */}
        <div>
          <label className={labelBase}>Preço mínimo</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mrv-text-dim text-xs font-semibold select-none">R$</span>
            <input
              type="text"
              value={precoMin}
              onChange={e => setPrecoMin(formatarMilhar(e.target.value))}
              placeholder="200.000"
              required
              className={`${inputBase} pl-9`}
            />
          </div>
        </div>

        {/* Preço máximo */}
        <div>
          <label className={labelBase}>Preço máximo</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mrv-text-dim text-xs font-semibold select-none">R$</span>
            <input
              type="text"
              value={precoMax}
              onChange={e => setPrecoMax(formatarMilhar(e.target.value))}
              placeholder="600.000"
              required
              className={`${inputBase} pl-9`}
            />
          </div>
        </div>

        {/* Tipologia */}
        <div>
          <label className={labelBase}>Tipologia</label>
          <select
            value={quartos}
            onChange={e => setQuartos(e.target.value)}
            title="Tipologia"
            aria-label="Tipologia"
            className={`${inputBase} cursor-pointer`}
          >
            <option value="">Qualquer</option>
            <option value="1">1 quarto</option>
            <option value="2">2 quartos</option>
            <option value="3">3 quartos</option>
            <option value="4">4+ quartos</option>
          </select>
        </div>

        {/* Botão de busca */}
        <div className="lg:col-span-6 flex justify-end pt-1">
          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 bg-mrv-orange hover:bg-mrv-orange-dark disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold px-7 py-2.5 rounded-card text-sm transition-all tracking-wide"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                Varrendo portais...
              </>
            ) : (
              <>
                <Search size={14} />
                Buscar concorrentes
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  )
}
