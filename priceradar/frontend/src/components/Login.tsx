import { useState } from 'react'
import { login } from '../api/client'

interface LoginProps {
  onAutenticado: () => void
}

export function Login({ onAutenticado }: LoginProps) {
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErro(null)
    setCarregando(true)
    try {
      await login(senha)
      onAutenticado()
    } catch {
      setErro('Senha incorreta.')
    } finally {
      setCarregando(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-mrv-base">
      <form onSubmit={handleSubmit} className="bg-mrv-surface border border-mrv-border rounded-panel p-8 w-full max-w-sm">
        <h1 className="font-bold text-lg text-mrv-text mb-4">
          Price<span className="text-mrv-orange">Radar</span>
        </h1>
        <input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          placeholder="Senha"
          autoFocus
          className="w-full mb-3 px-3 py-2 rounded-card bg-mrv-surface-2 border border-mrv-border text-mrv-text"
        />
        {erro && <p className="text-red-400 text-sm mb-3">{erro}</p>}
        <button
          type="submit"
          disabled={carregando}
          className="w-full bg-mrv-orange hover:bg-mrv-orange-dark disabled:opacity-40 text-white py-2 rounded-card font-semibold transition-colors"
        >
          {carregando ? 'Entrando...' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
