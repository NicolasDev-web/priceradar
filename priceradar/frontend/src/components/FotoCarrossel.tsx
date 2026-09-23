/**
 * Fotos do anúncio no topo do card, com tela cheia ao clicar.
 *
 * Só as fotos que vieram na página de resultados do portal — buscar a galeria
 * completa custaria uma requisição por anúncio, e é assim que os portais
 * reconhecem robô (decisão do PLANO_MELHORIAS.md, F1).
 *
 * Anúncio sem foto NÃO some: mostra uma ilustração com o selo "Foto
 * ilustrativa". O selo é o ponto — um desenho genérico sem aviso seria lido
 * como a fachada do prédio, e numa ferramenta de precificação isso é afirmar
 * o que o dado não diz.
 *
 * Foto que não carrega (hotlink bloqueado, link expirado) é pulada em silêncio;
 * se todas falharem, cai na ilustração do mesmo jeito.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, ImageOff, X } from 'lucide-react'

interface Props {
  fotos: string[] | undefined
  /** Usado no texto alternativo. */
  titulo: string
}

// Deslocamento mínimo para um arrasto contar como troca de foto — abaixo
// disso é toque para abrir a tela cheia.
const LIMIAR_SWIPE_PX = 40

// Setas: sempre visíveis no toque (não existe hover), só no hover com mouse.
const SETA =
  'absolute top-1/2 -translate-y-1/2 flex items-center justify-center w-7 h-7 rounded-full ' +
  'bg-black/55 text-white hover:bg-black/75 transition-opacity ' +
  'focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-mrv-green ' +
  '[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/foto:opacity-100'

function useFotosValidas(fotos: string[] | undefined) {
  const [quebradas, setQuebradas] = useState<Set<string>>(() => new Set())
  const validas = useMemo(
    () => (fotos ?? []).filter(f => !quebradas.has(f)),
    [fotos, quebradas],
  )
  const marcarQuebrada = useCallback((url: string) => {
    setQuebradas(prev => (prev.has(url) ? prev : new Set(prev).add(url)))
  }, [])
  return { validas, marcarQuebrada }
}

/** Arrasto horizontal em toque ou caneta. Mouse usa as setas. */
function useSwipe(onEsquerda: () => void, onDireita: () => void) {
  const inicioX = useRef<number | null>(null)
  const arrastou = useRef(false)
  return {
    arrastou,
    handlers: {
      onPointerDown: (ev: React.PointerEvent) => {
        if (ev.pointerType === 'mouse') return
        inicioX.current = ev.clientX
        arrastou.current = false
      },
      onPointerUp: (ev: React.PointerEvent) => {
        if (inicioX.current === null) return
        const dx = ev.clientX - inicioX.current
        inicioX.current = null
        if (Math.abs(dx) < LIMIAR_SWIPE_PX) return
        arrastou.current = true
        if (dx < 0) onEsquerda()
        else onDireita()
      },
      onPointerCancel: () => {
        inicioX.current = null
      },
    },
  }
}

function FotoIlustrativa() {
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center bg-mrv-surface-2 text-mrv-text-dim"
      role="img"
      aria-label="Foto ilustrativa: o anúncio não trouxe foto do imóvel"
      title="O anúncio não trouxe foto do imóvel — esta imagem é genérica"
    >
      {/* Silhueta de prédio desenhada à mão: genérica de propósito, para não
          ser confundida com foto. */}
      <svg viewBox="0 0 120 80" className="w-28" aria-hidden="true">
        <rect x="30" y="18" width="36" height="58" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" />
        <rect x="66" y="34" width="26" height="42" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" />
        {[0, 1, 2, 3, 4].map(l =>
          [0, 1, 2].map(c => (
            <rect key={`${l}-${c}`} x={36 + c * 9} y={24 + l * 10} width="5" height="5" fill="currentColor" opacity="0.6" />
          )),
        )}
        {[0, 1, 2].map(l =>
          [0, 1].map(c => (
            <rect key={`b${l}-${c}`} x={71 + c * 9} y={40 + l * 10} width="5" height="5" fill="currentColor" opacity="0.6" />
          )),
        )}
        <line x1="18" y1="76" x2="104" y2="76" stroke="currentColor" strokeWidth="2" />
      </svg>
      <span className="mt-2 flex items-center gap-1 text-[10px] font-medium">
        <ImageOff size={11} /> Anúncio sem foto
      </span>
      <span className="absolute top-2 left-2 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-mrv-orange text-white shadow">
        Foto ilustrativa
      </span>
    </div>
  )
}

function TelaCheia({
  fotos,
  indice,
  titulo,
  onTrocar,
  onFechar,
  onErro,
}: {
  fotos: string[]
  indice: number
  titulo: string
  onTrocar: (novo: number) => void
  onFechar: () => void
  onErro: (url: string) => void
}) {
  const total = fotos.length
  const anterior = useCallback(() => onTrocar((indice - 1 + total) % total), [indice, total, onTrocar])
  const proxima = useCallback(() => onTrocar((indice + 1) % total), [indice, total, onTrocar])
  const { handlers } = useSwipe(proxima, anterior)
  const fecharRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const anteriorFoco = document.activeElement as HTMLElement | null
    fecharRef.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = overflow
      anteriorFoco?.focus()
    }
  }, [])

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key === 'Escape') onFechar()
      else if (ev.key === 'ArrowLeft' && total > 1) anterior()
      else if (ev.key === 'ArrowRight' && total > 1) proxima()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [anterior, proxima, onFechar, total])

  // Portal para o body: o card tem animação com transform, e `position: fixed`
  // dentro de ancestral com transform fica preso ao card, não à tela.
  return createPortal(
    <div
      className="fixed inset-0 z-[1000] bg-black/90 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Fotos de ${titulo}`}
      onClick={onFechar}
    >
      <img
        key={fotos[indice]}
        src={fotos[indice]}
        alt={`Foto ${indice + 1} de ${total} — ${titulo}`}
        referrerPolicy="no-referrer"
        className="max-w-full max-h-full object-contain select-none touch-pan-y"
        draggable={false}
        onClick={ev => ev.stopPropagation()}
        onError={() => onErro(fotos[indice])}
        {...handlers}
      />
      <button
        ref={fecharRef}
        type="button"
        onClick={onFechar}
        className="absolute top-4 right-4 w-9 h-9 flex items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
        aria-label="Fechar"
      >
        <X size={18} />
      </button>
      {total > 1 && (
        <>
          <button
            type="button"
            onClick={ev => { ev.stopPropagation(); anterior() }}
            className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
            aria-label="Foto anterior"
          >
            <ChevronLeft size={22} />
          </button>
          <button
            type="button"
            onClick={ev => { ev.stopPropagation(); proxima() }}
            className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
            aria-label="Próxima foto"
          >
            <ChevronRight size={22} />
          </button>
        </>
      )}
      <span className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs font-data text-white/80 bg-black/50 px-2.5 py-1 rounded-full">
        {indice + 1} / {total}
      </span>
    </div>,
    document.body,
  )
}

export function FotoCarrossel({ fotos, titulo }: Props) {
  const { validas, marcarQuebrada } = useFotosValidas(fotos)
  const [indice, setIndice] = useState(0)
  const [telaCheia, setTelaCheia] = useState(false)
  const total = validas.length

  // Foto quebrada some da lista; o índice não pode ficar apontando para o vazio.
  const atual = total ? Math.min(indice, total - 1) : 0

  const anterior = useCallback(() => setIndice(i => (Math.min(i, total - 1) - 1 + total) % total), [total])
  const proxima = useCallback(() => setIndice(i => (Math.min(i, total - 1) + 1) % total), [total])
  const { arrastou, handlers } = useSwipe(proxima, anterior)

  useEffect(() => {
    if (!total) setTelaCheia(false)
  }, [total])

  if (!total) {
    return (
      <div className="relative aspect-[16/10] overflow-hidden">
        <FotoIlustrativa />
      </div>
    )
  }

  // A tela cheia fica FORA do div do carrossel: eventos React atravessam o
  // portal e subiriam até os handlers de swipe e teclado daqui, trocando a
  // foto duas vezes por toque.
  return (
    <>
      <div
        className="relative aspect-[16/10] overflow-hidden bg-mrv-surface-2 group/foto touch-pan-y"
        role="group"
        aria-roledescription="carrossel"
        aria-label={`Fotos de ${titulo}`}
        tabIndex={0}
        onKeyDown={ev => {
          if (ev.key === 'ArrowLeft' && total > 1) { ev.preventDefault(); anterior() }
          else if (ev.key === 'ArrowRight' && total > 1) { ev.preventDefault(); proxima() }
          else if (ev.key === 'Enter') setTelaCheia(true)
        }}
        {...handlers}
      >
        <button
          type="button"
          className="absolute inset-0 w-full h-full cursor-zoom-in"
          onClick={() => {
            // O toque que terminou um arrasto não é um clique para abrir.
            if (arrastou.current) { arrastou.current = false; return }
            setTelaCheia(true)
          }}
          aria-label="Ver fotos em tela cheia"
          tabIndex={-1}
        >
          <img
            key={validas[atual]}
            src={validas[atual]}
            alt={`Foto ${atual + 1} de ${total} — ${titulo}`}
            loading="lazy"
            decoding="async"
            // Vários CDNs de portal recusam imagem com Referer de outro site.
            referrerPolicy="no-referrer"
            draggable={false}
            className="w-full h-full object-cover select-none"
            onError={() => marcarQuebrada(validas[atual])}
          />
        </button>

        {total > 1 && (
          <>
            <button type="button" onClick={anterior} className={`${SETA} left-2`} aria-label="Foto anterior">
              <ChevronLeft size={16} />
            </button>
            <button type="button" onClick={proxima} className={`${SETA} right-2`} aria-label="Próxima foto">
              <ChevronRight size={16} />
            </button>
            <span className="absolute bottom-2 right-2 text-[10px] font-data font-semibold text-white bg-black/55 px-1.5 py-0.5 rounded pointer-events-none">
              {atual + 1}/{total}
            </span>
          </>
        )}
      </div>

      {telaCheia && (
        <TelaCheia
          fotos={validas}
          indice={atual}
          titulo={titulo}
          onTrocar={setIndice}
          onFechar={() => setTelaCheia(false)}
          onErro={marcarQuebrada}
        />
      )}
    </>
  )
}
