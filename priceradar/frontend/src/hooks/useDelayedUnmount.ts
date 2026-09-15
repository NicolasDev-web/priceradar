import { useEffect, useState } from 'react'

/**
 * Mantém um componente montado por `exitMs` depois que `isOpen` vira false,
 * dando tempo da animação de saída (CSS) rodar antes do React remover o nó
 * da árvore — o `&&` puro no chamador tira o elemento do DOM no mesmo
 * instante, antes de qualquer transição poder tocar.
 */
export function useDelayedUnmount(isOpen: boolean, exitMs: number): boolean {
  const [mounted, setMounted] = useState(isOpen)

  useEffect(() => {
    if (isOpen) {
      setMounted(true)
      return
    }
    const timer = setTimeout(() => setMounted(false), exitMs)
    return () => clearTimeout(timer)
  }, [isOpen, exitMs])

  return mounted
}
