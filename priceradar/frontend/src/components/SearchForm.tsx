import { Building2, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { listarBairros } from '../api/client'
import { CIDADES } from '../data/cidades'
import type { BuscaRequest } from '../types'

interface Props {
  onBuscar: (params: BuscaRequest) => void
  loading: boolean
}

function formatarMilhar(valor: string): string {
  const nums = valor.replace(/\D/g, '')
  return nums.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/** Remove acento para comparar: digitar "goiania" precisa achar "Goiânia". */
function semAcento(texto: string): string {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()
}

const MAX_SUGESTOES_CIDADE = 8
// Bairro precisa de mais: uma cidade grande passa de 50 bairros com oferta, e
// 8 linhas escondem justamente o bairro menos óbvio que se está procurando.
const MAX_SUGESTOES_BAIRRO = 12

const inputBase =
  'w-full bg-mrv-base border border-mrv-border rounded-card px-4 py-2.5 text-sm text-mrv-text placeholder-mrv-text-dim ' +
  'focus:outline-none focus:border-mrv-green focus:ring-1 focus:ring-mrv-green/30 transition-all ' +
  'font-sans'

const labelBase =
  'block text-[10px] font-semibold text-mrv-text-dim mb-1.5 uppercase tracking-[0.1em]'

export function SearchForm({ onBuscar, loading }: Props) {
  const [cidade, setCidade] = useState('Fortaleza, CE')
  const [bairros, setBairros] = useState<string[]>([])
  const [bairroDigitando, setBairroDigitando] = useState('')
  const [precoMin, setPrecoMin] = useState('280.000')
  const [precoMax, setPrecoMax] = useState('500.000')
  const [quartos, setQuartos] = useState<string>('')
  const [tipoEdificacao, setTipoEdificacao] = useState<string>('')
  const [mostrarSugestoes, setMostrarSugestoes] = useState(false)
  const [bairrosDaCidade, setBairrosDaCidade] = useState<string[]>([])
  const [mostrarBairros, setMostrarBairros] = useState(false)
  const cidadeRef = useRef<HTMLInputElement>(null)

  // Bairros com oferta na cidade escolhida. Só busca quando a cidade está
  // completa ("Cidade, UF"), e com debounce de 300ms — sem isso, corrigir
  // algo antes da vírgula ("Fortaleza, C" → "Fortaleza, CE") dispara uma
  // requisição a cada tecla.
  useEffect(() => {
    const partes = cidade.split(',')
    if (partes.length < 2 || partes[1].trim().length !== 2) {
      setBairrosDaCidade([])
      return
    }
    const timer = setTimeout(() => {
      listarBairros(cidade).then(bs => setBairrosDaCidade(bs))
    }, 300)
    return () => clearTimeout(timer)
  }, [cidade])

  // Não sugere o que já foi escolhido, e filtra pelo que está sendo digitado.
  const sugestoesBairro = useMemo(() => {
    const termo = semAcento(bairroDigitando)
    const jaEscolhidos = new Set(bairros.map(semAcento))
    return bairrosDaCidade
      .filter(b => !jaEscolhidos.has(semAcento(b)))
      .filter(b => !termo || semAcento(b).includes(termo))
      .slice(0, MAX_SUGESTOES_BAIRRO)
  }, [bairrosDaCidade, bairroDigitando, bairros])

  // Ao focar sem ter digitado nada, mostra as maiores cidades — a lista já
  // vem ordenada por população, então são as praças mais prováveis.
  //
  // Prefixo primeiro, substring depois: só `startsWith` faria "andre" não
  // achar "Santo André" e "conquista" não achar "Vitória da Conquista". Só
  // `includes` afundaria a cidade certa sob homônimos parciais. As duas
  // partições mantêm a ordem por população dentro de si.
  const sugestoes = useMemo(() => {
    const termo = semAcento(cidade.split(',')[0])
    if (!termo) return CIDADES.slice(0, MAX_SUGESTOES_CIDADE)
    const comecam: typeof CIDADES[number][] = []
    const contem: typeof CIDADES[number][] = []
    for (const c of CIDADES) {
      if (c[2].startsWith(termo)) comecam.push(c)
      else if (c[2].includes(termo)) contem.push(c)
      if (comecam.length >= MAX_SUGESTOES_CIDADE) break
    }
    return [...comecam, ...contem].slice(0, MAX_SUGESTOES_CIDADE)
  }, [cidade])

  function parseMoeda(s: string): number {
    return parseFloat(s.replace(/\./g, '').replace(',', '.')) || 0
  }

  function selecionarCidade(nome: string, uf: string) {
    // Preenche já no formato "Cidade, UF" que a API exige — é o que elimina
    // o erro de buscar sem o estado.
    setCidade(`${nome}, ${uf}`)
    setMostrarSugestoes(false)
    cidadeRef.current?.blur()
  }

  function adicionarBairro(valor: string) {
    const limpo = valor.trim().replace(/,$/, '').trim()
    if (!limpo) return
    if (bairros.some(b => semAcento(b) === semAcento(limpo))) return
    setBairros([...bairros, limpo])
    setBairroDigitando('')
  }

  function handleBairroKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      adicionarBairro(bairroDigitando)
    } else if (e.key === 'Backspace' && !bairroDigitando && bairros.length) {
      setBairros(bairros.slice(0, -1))
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    // Um bairro ainda não confirmado no campo entra na busca mesmo assim —
    // digitar e clicar em buscar direto é o fluxo natural.
    const todos = bairroDigitando.trim() ? [...bairros, bairroDigitando.trim()] : bairros
    onBuscar({
      cidade,
      preco_min: parseMoeda(precoMin),
      preco_max: parseMoeda(precoMax),
      quartos: quartos ? parseInt(quartos) : null,
      bairros: todos.length ? todos : null,
      tipo_edificacao: tipoEdificacao || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="bg-mrv-surface border border-mrv-border rounded-panel p-5 mb-5">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-12 gap-4 items-start">

        {/* Cidade com sugestão */}
        <div className="lg:col-span-3 relative">
          <label className={labelBase}>
            Cidade{' '}
            <span className="normal-case text-mrv-text-dim font-normal">(com a UF)</span>
          </label>
          <input
            ref={cidadeRef}
            type="text"
            value={cidade}
            onChange={e => { setCidade(e.target.value); setMostrarSugestoes(true) }}
            onFocus={() => setMostrarSugestoes(true)}
            onBlur={() => setTimeout(() => setMostrarSugestoes(false), 150)}
            placeholder="Ex: Campinas, SP"
            required
            autoComplete="off"
            className={inputBase}
          />
          {mostrarSugestoes && sugestoes.length > 0 && (
            <ul className="absolute z-20 left-0 right-0 mt-1 bg-mrv-surface-2 border border-mrv-border rounded-card shadow-xl overflow-hidden max-h-64 overflow-y-auto">
              {sugestoes.map(([nome, uf]) => (
                <li key={`${nome}-${uf}`}>
                  <button
                    type="button"
                    onMouseDown={e => e.preventDefault()}
                    onClick={() => selecionarCidade(nome, uf)}
                    className="w-full text-left px-4 py-2 text-sm text-mrv-text hover:bg-mrv-green/20 transition-colors flex items-center justify-between gap-2"
                  >
                    <span>{nome}</span>
                    <span className="text-[10px] text-mrv-text-dim font-semibold">{uf}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-mrv-text-dim mt-1">
            Municípios do Nordeste — o campo aceita qualquer cidade digitada.
          </p>
        </div>

        {/* Bairros (vários) */}
        <div className="lg:col-span-3 relative">
          <label className={labelBase}>
            Bairros{' '}
            <span className="normal-case text-mrv-text-dim font-normal">(opc.)</span>
          </label>
          <div className={`${inputBase} flex flex-wrap items-center gap-1.5 min-h-[42px] py-1.5`}>
            {bairros.map(b => (
              <span
                key={b}
                className="flex items-center gap-1 bg-mrv-green/25 border border-mrv-green/40 text-mrv-text text-[11px] font-medium px-2 py-0.5 rounded-full"
              >
                {b}
                <button
                  type="button"
                  onClick={() => setBairros(bairros.filter(x => x !== b))}
                  className="text-mrv-text-muted hover:text-mrv-text"
                  aria-label={`Remover ${b}`}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            <input
              type="text"
              value={bairroDigitando}
              onChange={e => { setBairroDigitando(e.target.value); setMostrarBairros(true) }}
              onKeyDown={handleBairroKeyDown}
              onFocus={() => setMostrarBairros(true)}
              onBlur={() => setTimeout(() => {
                adicionarBairro(bairroDigitando)
                setMostrarBairros(false)
              }, 150)}
              placeholder={bairros.length ? '' : 'Ex: Aldeota, Meireles'}
              autoComplete="off"
              className="flex-1 min-w-[80px] bg-transparent outline-none text-sm placeholder-mrv-text-dim"
            />
          </div>

          {/* Bairros da cidade escolhida, vindos dos próprios portais —
              são os que têm oferta, não uma lista administrativa. */}
          {mostrarBairros && sugestoesBairro.length > 0 && (
            <ul className="absolute z-20 left-0 right-0 mt-1 bg-mrv-surface-2 border border-mrv-border rounded-card shadow-xl overflow-hidden max-h-56 overflow-y-auto">
              {sugestoesBairro.map(b => (
                <li key={b}>
                  <button
                    type="button"
                    onMouseDown={e => e.preventDefault()}
                    onClick={() => { adicionarBairro(b); setMostrarBairros(false) }}
                    className="w-full text-left px-4 py-2 text-sm text-mrv-text hover:bg-mrv-green/20 transition-colors"
                  >
                    {b}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <p className="text-[10px] text-mrv-text-dim mt-1">
            {bairrosDaCidade.length
              ? `${bairrosDaCidade.length} bairros com oferta. Vários = comparativo.`
              : 'Enter ou vírgula para adicionar. Vários bairros = comparativo.'}
          </p>
        </div>

        {/* Preço mínimo */}
        <div className="lg:col-span-2">
          <label className={labelBase}>Preço mínimo</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mrv-text-dim text-xs">R$</span>
            <input
              type="text"
              value={precoMin}
              onChange={e => setPrecoMin(formatarMilhar(e.target.value))}
              className={`${inputBase} pl-9`}
            />
          </div>
        </div>

        {/* Preço máximo */}
        <div className="lg:col-span-2">
          <label className={labelBase}>Preço máximo</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-mrv-text-dim text-xs">R$</span>
            <input
              type="text"
              value={precoMax}
              onChange={e => setPrecoMax(formatarMilhar(e.target.value))}
              className={`${inputBase} pl-9`}
            />
          </div>
        </div>

        {/* Tipologia */}
        <div className="lg:col-span-1">
          <label className={labelBase}>Quartos</label>
          <select value={quartos} onChange={e => setQuartos(e.target.value)} className={inputBase}>
            <option value="">Todos</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
            <option value="4">4+</option>
          </select>
        </div>

        {/* Torre x bloco */}
        <div className="lg:col-span-1">
          <label className={labelBase} title="Torre tem elevador; bloco não">
            Prédio
          </label>
          <select
            value={tipoEdificacao}
            onChange={e => setTipoEdificacao(e.target.value)}
            className={inputBase}
          >
            <option value="">Todos</option>
            <option value="torre">Torre</option>
            <option value="provavel_bloco">Bloco</option>
            <option value="indefinido">Sem info</option>
          </select>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
        {tipoEdificacao === 'torre' && (
          <p className="text-[11px] text-mrv-text-muted flex items-center gap-1.5">
            <Building2 size={12} className="text-mrv-text-dim" />
            Torre = elevador declarado no anúncio ou unidade acima do 5º andar.
          </p>
        )}
        {tipoEdificacao === 'provavel_bloco' && (
          <p className="text-[11px] text-amber-300/80 flex items-center gap-1.5">
            <Building2 size={12} />
            Inferido de anúncios até o 4º andar sem elevador — nenhum portal declara "sem elevador".
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="ml-auto flex items-center gap-2 bg-mrv-orange hover:bg-mrv-orange-dark disabled:opacity-40 text-white font-semibold text-sm px-6 py-2.5 rounded-card transition-colors"
        >
          <Search size={15} />
          {loading ? 'Buscando...' : 'Buscar concorrentes'}
        </button>
      </div>
    </form>
  )
}
