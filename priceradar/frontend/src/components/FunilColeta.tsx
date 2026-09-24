/**
 * "Por que vieram só N?" — do bruto coletado ao que aparece na tela.
 *
 * Existe para a F4.6 do PLANO_MELHORIAS.md: só dá para afrouxar uma regra de
 * descarte com número na mão, e até aqui o número morava só na API. Fechado
 * por padrão: é para quem vai investigar, não para a leitura do resultado.
 *
 * Duplicata aparece separada das regras de qualidade: o mesmo imóvel em dois
 * portais não é mercado perdido, e somar tudo junto faria parecer que a busca
 * joga fora metade do que acha.
 */
import { Filter } from 'lucide-react'
import type { DiagnosticoColeta } from '../types'

const ROTULOS: Record<string, string> = {
  duplicata_mesma_url: 'Repetido no mesmo portal',
  duplicata_outro_portal: 'Mesmo imóvel em outro portal',
  locacao: 'Anúncio de aluguel',
  sem_preco: 'Sem preço',
  preco_nao_e_total: 'Preço de parcela/entrada',
  titulo_invalido: 'Título inválido',
  sem_area: 'Sem área',
  area_implausivel: 'Área implausível',
  faixa_de_area: 'Fora da faixa de área',
  preco_m2_implausivel: 'Preço/m² implausível',
  tipologia_divergente: 'Outro nº de quartos',
  banheiros_divergente: 'Outro nº de banheiros',
  fora_da_faixa_preco: 'Fora da faixa de preço',
  outro_tipo_edificacao: 'Outro tipo de prédio (torre/bloco)',
  fora_dos_bairros: 'Fora dos bairros pedidos',
  titulo_e_preco: 'Título era só um preço',
  preco_m2_fora_do_grupo: 'Preço/m² muito fora dos demais',
  rejeitado_rf: 'Rejeitado pelo modelo (anomalia)',
}

const DUPLICATAS = new Set(['duplicata_mesma_url', 'duplicata_outro_portal'])

interface Props {
  diagnostico: DiagnosticoColeta
  exibidos: number
}

export function FunilColeta({ diagnostico, exibidos }: Props) {
  const motivos = Object.entries(diagnostico.descartados_por_motivo ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
  if (!diagnostico.total_bruto || !motivos.length) return null

  const duplicatas = motivos.filter(([m]) => DUPLICATAS.has(m))
  const regras = motivos.filter(([m]) => !DUPLICATAS.has(m))
  const totalRegras = regras.reduce((s, [, n]) => s + n, 0)
  const totalDup = duplicatas.reduce((s, [, n]) => s + n, 0)

  const linha = ([motivo, n]: [string, number]) => (
    <li key={motivo} className="flex justify-between gap-4">
      <span>{ROTULOS[motivo] ?? motivo}</span>
      <span className="font-data text-mrv-text">{n}</span>
    </li>
  )

  return (
    <details className="bg-mrv-surface border border-mrv-border rounded-card px-4 py-2.5 mb-4 text-[12px] text-mrv-text-muted group">
      <summary className="cursor-pointer select-none flex items-center gap-2 list-none">
        <Filter size={13} className="text-mrv-text-dim" />
        <span>
          <span className="font-data text-mrv-text">{diagnostico.total_bruto}</span> coletados →{' '}
          <span className="font-data text-mrv-text">{exibidos}</span> exibidos
          {totalDup > 0 && <> · {totalDup} duplicatas</>}
          {totalRegras > 0 && <> · {totalRegras} descartados por regra</>}
        </span>
        <span className="ml-auto text-mrv-text-dim group-open:hidden">ver motivos</span>
      </summary>
      <div className="grid sm:grid-cols-2 gap-x-8 gap-y-3 mt-3 pb-1">
        {regras.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-[0.1em] text-mrv-text-dim mb-1.5">Regras de qualidade e filtros</p>
            <ul className="space-y-1">{regras.map(linha)}</ul>
          </div>
        )}
        {duplicatas.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-[0.1em] text-mrv-text-dim mb-1.5">Duplicatas (não é mercado perdido)</p>
            <ul className="space-y-1">{duplicatas.map(linha)}</ul>
          </div>
        )}
      </div>
    </details>
  )
}
