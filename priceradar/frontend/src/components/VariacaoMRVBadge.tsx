interface Props {
  variacao: number | null
}

export function VariacaoMRVBadge({ variacao }: Props) {
  if (variacao === null) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-mrv-surface-2/60 text-mrv-text-dim font-medium">
        Sem ref. MRV
      </span>
    )
  }

  let bg: string
  let icon: string
  let label: string

  const abs = Math.abs(variacao).toFixed(1)

  if (variacao <= -15) {
    bg = 'bg-red-950/60 text-red-400 border border-red-800/40'
    icon = '▼'
    label = `${abs}% abaixo da MRV`
  } else if (variacao < -5) {
    bg = 'bg-orange-950/60 text-orange-400 border border-orange-800/40'
    icon = '▼'
    label = `${abs}% abaixo da MRV`
  } else if (variacao <= 5) {
    bg = 'bg-mrv-surface-2/60 text-mrv-text-muted border border-mrv-border'
    icon = variacao >= 0 ? '▲' : '▼'
    label = variacao === 0 ? 'Paridade MRV' : `${abs}% ${variacao >= 0 ? 'acima' : 'abaixo'} da MRV`
  } else {
    bg = 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
    icon = '▲'
    label = `${abs}% acima da MRV`
  }

  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-semibold ${bg}`}>
      {icon} {label}
    </span>
  )
}
