/**
 * Formatação compartilhada pelos gráficos de evolução (cidade e bairros).
 *
 * O backend agrupa por semana no formato do SQLite '%Y-W%W': a semana 1
 * começa na primeira segunda-feira do ano e os dias antes dela são a semana 0.
 * Esse número não bate com o calendário ISO que o usuário conhece, então a tela
 * mostra as datas da semana em vez dele.
 */

const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]

const DIA_MS = 24 * 60 * 60 * 1000

export function formatarMoeda(v: number): string {
  return `R$ ${v.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

/** Eixo Y: 9.527 → "R$ 9,5 mil". Uma casa para 2.500 não virar "R$ 3k". */
export function formatarEixoMoeda(v: number): string {
  return `R$ ${(v / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`
}

export function pluralAnuncios(total: number): string {
  return `${total} ${total === 1 ? 'anúncio' : 'anúncios'}`
}

/**
 * Primeiro e último dia da semana '%Y-W%W', em UTC. Recortado ao próprio ano:
 * a semana 0 de 2026 vai de 1º a 4 de janeiro, e 29–31/12 ficam na última
 * semana de 2025 — é exatamente o que o backend agrupou em cada ponto.
 */
export function intervaloDaSemana(semana: string): { inicio: Date; fim: Date } | null {
  const m = semana.match(/^(\d{4})-W(\d{1,2})$/)
  if (!m) return null
  const ano = Number(m[1])
  const numero = Number(m[2])
  const primeiroDia = Date.UTC(ano, 0, 1)
  const diaDaSemana = new Date(primeiroDia).getUTCDay() // 0 = domingo
  const primeiraSegunda = primeiroDia + ((8 - diaDaSemana) % 7) * DIA_MS
  const segunda = primeiraSegunda + (numero - 1) * 7 * DIA_MS
  const inicio = Math.max(segunda, primeiroDia)
  const fim = Math.min(segunda + 6 * DIA_MS, Date.UTC(ano, 11, 31))
  if (fim < inicio) return null
  return { inicio: new Date(inicio), fim: new Date(fim) }
}

function doisDigitos(n: number): string {
  return String(n).padStart(2, '0')
}

/** Eixo X: '2026-W36' → "07/09" (primeiro dia da semana). */
export function rotuloSemana(semana: string): string {
  const intervalo = intervaloDaSemana(semana)
  if (!intervalo) return semana
  const { inicio } = intervalo
  return `${doisDigitos(inicio.getUTCDate())}/${doisDigitos(inicio.getUTCMonth() + 1)}`
}

/** Tooltip: '2026-W36' → "Semana de 7 a 13 de setembro de 2026". */
export function descricaoSemana(semana: string): string {
  const intervalo = intervaloDaSemana(semana)
  if (!intervalo) return semana
  const { inicio, fim } = intervalo
  const ano = fim.getUTCFullYear()
  const mesFim = MESES[fim.getUTCMonth()]
  if (inicio.getTime() === fim.getTime()) {
    return `Dia ${fim.getUTCDate()} de ${mesFim} de ${ano}`
  }
  const mesmoMes = inicio.getUTCMonth() === fim.getUTCMonth()
  const de = mesmoMes ? `${inicio.getUTCDate()}` : `${inicio.getUTCDate()} de ${MESES[inicio.getUTCMonth()]}`
  return `Semana de ${de} a ${fim.getUTCDate()} de ${mesFim} de ${ano}`
}
