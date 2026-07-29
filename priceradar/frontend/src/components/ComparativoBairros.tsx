import { AlertTriangle } from 'lucide-react'
import type { ResumoBairro } from '../types'

interface Props {
  dados: ResumoBairro[]
  /** Abaixo disso a mediana do bairro não sustenta decisão. */
  minimoConfiavel: number
}

function moeda(v: number): string {
  return v.toLocaleString('pt-BR', {
    style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0,
  })
}

/**
 * Comparativo lado a lado por bairro.
 *
 * Existe porque uma mediana única sobre vários bairros esconde justamente a
 * diferença que a análise procura: Aldeota e Messejana num número só não
 * respondem "onde compensa lançar?".
 */
export function ComparativoBairros({ dados, minimoConfiavel }: Props) {
  if (dados.length < 2) return null

  const maiorMediana = Math.max(...dados.map(d => d.preco_m2_mediana))

  return (
    <div className="bg-mrv-surface border border-mrv-border rounded-panel p-5 mb-6">
      <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em] mb-4">
        Comparativo por bairro
      </h2>

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[520px]">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-mrv-text-dim">
              <th className="text-left font-semibold pb-2">Bairro</th>
              <th className="text-right font-semibold pb-2">Anúncios</th>
              <th className="text-right font-semibold pb-2">Preço/m² mediano</th>
              <th className="text-right font-semibold pb-2 hidden sm:table-cell">Faixa</th>
            </tr>
          </thead>
          <tbody>
            {dados.map(b => {
              const amostraFraca = b.total < minimoConfiavel
              return (
                <tr key={b.bairro} className="border-t border-mrv-border/60">
                  <td className="py-2.5 pr-3">
                    <span className="font-medium text-mrv-text">{b.bairro}</span>
                    {amostraFraca && (
                      <span
                        className="ml-2 inline-flex items-center gap-1 text-[10px] text-amber-300/90"
                        title={`Só ${b.total} anúncios — a mediana deste bairro é frágil`}
                      >
                        <AlertTriangle size={10} />
                        amostra fraca
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 text-right font-data text-mrv-text-muted">{b.total}</td>
                  <td className="py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {/* Barra proporcional: a comparação visual é o ponto da tabela */}
                      <span
                        className="hidden md:block h-1.5 rounded-full bg-mrv-green"
                        style={{ width: `${Math.round((b.preco_m2_mediana / maiorMediana) * 90)}px` }}
                      />
                      <span className={`font-data font-bold ${amostraFraca ? 'text-mrv-text-muted' : 'text-mrv-text'}`}>
                        {moeda(b.preco_m2_mediana)}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 text-right text-[11px] text-mrv-text-dim font-data hidden sm:table-cell">
                    {moeda(b.preco_m2_min)} – {moeda(b.preco_m2_max)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
