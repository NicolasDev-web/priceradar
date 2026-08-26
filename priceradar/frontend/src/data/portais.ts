// Configuração de todos os portais suportados — nome amigável e cor de chip.
// Compartilhado entre App.tsx (diagnóstico da coleta) e LoadingState.tsx
// (progresso da busca em andamento).
export const PORTAL_CONFIG: Record<string, { label: string; color: string }> = {
  vivareal:     { label: 'VivaReal',     color: 'bg-emerald-900/60 text-emerald-300 border border-emerald-700/40' },
  zapimoveis:   { label: 'ZAP',          color: 'bg-amber-900/60 text-amber-300 border border-amber-700/40' },
  chavesnamao:  { label: 'ChavesNaMão',  color: 'bg-rose-900/60 text-rose-300 border border-rose-700/40' },
  imovelweb:    { label: 'ImovelWeb',    color: 'bg-sky-900/60 text-sky-300 border border-sky-700/40' },
  olx:          { label: 'OLX',          color: 'bg-indigo-900/60 text-indigo-300 border border-indigo-700/40' },
  quintoandar:  { label: 'QuintoAndar',  color: 'bg-teal-900/60 text-teal-300 border border-teal-700/40' },
  netimoveis:   { label: 'NetImóveis',   color: 'bg-violet-900/60 text-violet-300 border border-violet-700/40' },
  mercadolivre: { label: 'Mercado Livre',color: 'bg-yellow-900/60 text-yellow-300 border border-yellow-700/40' },
}

export const LABEL_PORTAL = (p: string) => PORTAL_CONFIG[p]?.label ?? p
