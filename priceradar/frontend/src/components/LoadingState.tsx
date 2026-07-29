export function LoadingState() {
  return (
    <div className="w-full space-y-5 mt-4">

      {/* Status de varredura */}
      <div className="flex items-center gap-3 justify-center py-3">
        {/* Radar pulsante pequeno */}
        <div className="relative w-5 h-5">
          <div className="absolute inset-0 rounded-full border border-mrv-border animate-ping opacity-40" />
          <div className="absolute inset-1 rounded-full bg-mrv-orange/80" />
        </div>
        <span className="text-sm font-medium text-mrv-text-muted tracking-wide">
          Varrendo portais imobiliários
          <span className="inline-flex gap-0.5 ml-1">
            <span className="animate-bounce [animation-delay:0ms]">.</span>
            <span className="animate-bounce [animation-delay:150ms]">.</span>
            <span className="animate-bounce [animation-delay:300ms]">.</span>
          </span>
        </span>
      </div>

      {/* KPI skeletons */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className={`rounded-card p-5 border border-mrv-border animate-pulse ${
              i === 0 ? 'bg-mrv-green/20' : 'bg-mrv-surface'
            }`}
          >
            <div className="h-2 bg-mrv-surface-2/80 rounded w-3/4 mb-4" />
            <div className="h-8 bg-mrv-surface-2/60 rounded w-2/3 mb-2" />
            <div className="h-2 bg-mrv-surface-2/40 rounded w-1/2" />
          </div>
        ))}
      </div>

      {/* Chart skeleton */}
      <div className="bg-mrv-surface border border-mrv-border rounded-panel p-6 animate-pulse">
        <div className="h-3 bg-mrv-surface-2/80 rounded w-1/4 mb-6" />
        <div className="flex items-end gap-1.5 h-40">
          {Array.from({ length: 12 }).map((_, i) => (
            <div
              key={i}
              className="flex-1 bg-mrv-surface-2/60 rounded-t"
              style={{ height: `${30 + Math.sin(i * 0.8) * 25 + (i % 3) * 15}%` }}
            />
          ))}
        </div>
      </div>

      {/* Card skeletons */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="bg-mrv-surface border border-mrv-border rounded-card overflow-hidden animate-pulse flex">
            {/* Barra lateral skeleton */}
            <div className="w-1 bg-mrv-surface-2/80 flex-shrink-0" />
            <div className="flex-1 p-4">
              <div className="h-3.5 bg-mrv-surface-2/80 rounded w-4/5 mb-2" />
              <div className="h-2.5 bg-mrv-surface-2/50 rounded w-1/2 mb-4" />
              <div className="flex gap-2 mb-4">
                <div className="h-4 bg-mrv-surface-2/60 rounded-full w-16" />
                <div className="h-4 bg-mrv-surface-2/40 rounded-full w-20" />
              </div>
              <div className="h-px bg-mrv-border/50 mb-3" />
              <div className="flex gap-4 mb-4">
                <div className="h-2.5 bg-mrv-surface-2/50 rounded w-14" />
                <div className="h-2.5 bg-mrv-surface-2/40 rounded w-14" />
              </div>
              <div className="h-px bg-mrv-border/50 mb-3" />
              <div className="h-6 bg-mrv-surface-2/60 rounded w-2/5" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
