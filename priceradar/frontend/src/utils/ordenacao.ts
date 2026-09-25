/**
 * Ordenação dos cards (F4.7 do PLANO_MELHORIAS.md).
 *
 * Padrão: preço/m² crescente — é a pergunta do produto ("quem está mais
 * barato por m²?"). As outras ordens existem para investigar, e toda ordem
 * pode ser invertida.
 */
import type { Empreendimento } from '../types'

export type CriterioOrdem = 'preco_m2' | 'preco' | 'area' | 'completude'
export type Direcao = 'asc' | 'desc'

export const CRITERIOS: { valor: CriterioOrdem; rotulo: string; asc: string; desc: string }[] = [
  { valor: 'preco_m2', rotulo: 'Preço/m²', asc: 'mais barato primeiro', desc: 'mais caro primeiro' },
  { valor: 'preco', rotulo: 'Preço total', asc: 'mais barato primeiro', desc: 'mais caro primeiro' },
  { valor: 'area', rotulo: 'Área', asc: 'menor primeiro', desc: 'maior primeiro' },
  { valor: 'completude', rotulo: 'Mais completos', asc: 'mais completos primeiro', desc: 'menos completos primeiro' },
]

/** Quanto do anúncio veio preenchido. Foto e localização pesam mais: são o
 *  que falta com mais frequência e o que mais ajuda a avaliar o imóvel. */
export function completude(e: Empreendimento): number {
  return (
    (e.fotos?.length ? 3 : 0) +
    (e.latitude != null && e.origem_coordenada !== 'centroide_bairro' ? 2 : 0) +
    (e.bairro ? 1 : 0) +
    (e.construtora ? 1 : 0) +
    (e.quartos != null ? 1 : 0) +
    (e.banheiros != null ? 1 : 0) +
    (e.vagas != null ? 1 : 0)
  )
}

export function ordenar(lista: Empreendimento[], criterio: CriterioOrdem, direcao: Direcao): Empreendimento[] {
  const sinal = direcao === 'asc' ? 1 : -1
  const chave: (e: Empreendimento) => number =
    criterio === 'preco' ? e => e.preco
    : criterio === 'area' ? e => e.area_m2
    // "asc" em completude = mais completo primeiro, por isso o negativo.
    : criterio === 'completude' ? e => -completude(e)
    : e => e.preco_m2
  // Desempate estável por preço/m² crescente: a mesma ordem a cada render.
  return [...lista].sort((a, b) => sinal * (chave(a) - chave(b)) || a.preco_m2 - b.preco_m2)
}
