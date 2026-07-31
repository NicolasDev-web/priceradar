/**
 * Faixas de desvio do preço/m² em relação à média da busca.
 *
 * Vive aqui porque o card e o mapa mostram o MESMO número: se cada um tivesse
 * sua escala, o anúncio verde na lista poderia virar um pino laranja no mapa e
 * a tela passaria a falar duas línguas sobre o mesmo dado. Mudar um limiar
 * aqui muda os dois de uma vez.
 *
 * O mapa precisa de hex porque `pathOptions` do Leaflet desenha SVG e não
 * enxerga classe do Tailwind; o card precisa da classe. Por isso as duas
 * formas convivem numa faixa só.
 */

export interface Faixa {
  /** Classe Tailwind da barra lateral do card. */
  barColor: string
  /** Cor do texto de variação no card. */
  pctColor: string
  /** Fundo do badge de variação no card. */
  pctBg: string
  /** O mesmo tom em hex, para o SVG do mapa. */
  hex: string
}

/** Da mais barata para a mais cara. O limite é o teto de `pct` da faixa. */
const FAIXAS: { ate: number; faixa: Faixa }[] = [
  {
    ate: -8,
    faixa: {
      barColor: 'bg-emerald-500',
      pctColor: 'text-emerald-400',
      pctBg: 'bg-emerald-950/70 border border-emerald-800/50',
      hex: '#10B981',
    },
  },
  {
    ate: -2,
    faixa: {
      barColor: 'bg-emerald-700',
      pctColor: 'text-emerald-500',
      pctBg: 'bg-emerald-950/50 border border-emerald-900/50',
      hex: '#047857',
    },
  },
  {
    ate: 2,
    faixa: {
      barColor: 'bg-amber-500',
      pctColor: 'text-amber-400',
      pctBg: 'bg-amber-950/70 border border-amber-800/50',
      hex: '#F59E0B',
    },
  },
  {
    ate: 8,
    faixa: {
      barColor: 'bg-orange-600',
      pctColor: 'text-orange-400',
      pctBg: 'bg-orange-950/60 border border-orange-800/50',
      hex: '#EA580C',
    },
  },
  {
    ate: Infinity,
    faixa: {
      barColor: 'bg-red-500',
      pctColor: 'text-red-400',
      pctBg: 'bg-red-950/60 border border-red-800/50',
      hex: '#EF4444',
    },
  },
]

/** Desvio percentual do preço/m² em relação à média da busca. */
export function desvioPercentual(precoM2: number, media: number): number {
  if (!media) return 0
  return ((precoM2 - media) / media) * 100
}

export function faixaPorDesvio(pct: number): Faixa {
  // -8 e -2 são exclusivos; +2 e +8 inclusivos — como o card sempre fez.
  if (pct < -8) return FAIXAS[0].faixa
  if (pct < -2) return FAIXAS[1].faixa
  if (pct <= 2) return FAIXAS[2].faixa
  if (pct <= 8) return FAIXAS[3].faixa
  return FAIXAS[4].faixa
}

export function faixaPorPreco(precoM2: number, media: number): Faixa {
  return faixaPorDesvio(desvioPercentual(precoM2, media))
}

/** `-9.3%` / `+4.1%` — o sinal explícito no positivo. */
export function rotuloDesvio(pct: number): string {
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}
