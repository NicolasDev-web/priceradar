/**
 * Mapa dos anúncios da busca.
 *
 * Responde a mesma pergunta do ComparativoBairros — "onde?" — em forma
 * espacial: onde o preço/m² sobe e desce dentro da cidade, sem depender de
 * quem lê conhecer a geografia de cabeça.
 *
 * Três decisões que o dado obriga:
 *
 * 1. **Um marcador por COORDENADA, não por anúncio.** Quem foi posicionado
 *    pelo centro do bairro recebe exatamente o mesmo par de floats que todos
 *    os vizinhos. Desenhando um marcador por anúncio, vinte anúncios do
 *    ChavesNaMão no Meireles viram um pino só e dezenove ficam invisíveis e
 *    inclicáveis — perda silenciosa de um terço da base. Aqui eles viram um
 *    círculo com o número escrito nele.
 *    Espalhar com jitter foi descartado: inventaria uma dispersão que o dado
 *    não tem, desenhada com a mesma autoridade dos pinos reais.
 *
 * 2. **Estimativa não se veste de endereço.** `centroide_bairro` sai oco e
 *    tracejado, e o popup diz de onde veio o ponto.
 *
 * 3. **Quem ficou de fora é dito em voz alta.** Sem o contador, um mapa com
 *    quarenta pinos ao lado de uma lista de sessenta cards parece defeito.
 *
 * Os pinos são `CircleMarker` (SVG) e não `Marker`: a cor É a informação, um
 * PNG fixo não codifica preço/m² — e de quebra evita o ícone padrão do
 * Leaflet, que o Vite não emite e que renderiza como 404.
 */
import { useEffect, useMemo } from 'react'
import { AlertTriangle, ExternalLink, MapPin } from 'lucide-react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

import type { Empreendimento, OrigemCoordenada } from '../types'
import { desvioPercentual, faixaPorPreco, rotuloDesvio } from '../utils/posicionamento'

interface Props {
  empreendimentos: Empreendimento[]
  precoM2Medio: number
  /** Anúncios que não puderam ser posicionados. */
  semLocalizacao: number
  /** Quantos vieram com coordenada do portal, antes de qualquer estimativa. */
  comCoordenada?: number
}

const PORTAL_LABEL: Record<string, string> = {
  vivareal: 'VivaReal',
  zapimoveis: 'ZAP',
  chavesnamao: 'ChavesNaMão',
  imovelweb: 'ImovelWeb',
  olx: 'OLX',
  quintoandar: 'QuintoAndar',
  netimoveis: 'NetImóveis',
  mercadolivre: 'Mercado Livre',
}

/** Mesmos dados do OpenStreetMap, desenhados para fundo escuro. O tile branco
 *  padrão brilharia como um retângulo de luz no meio do painel.
 *
 *  A CARTO aposentou o acesso livre aos tiles raster — sem `key` na URL, o
 *  "tile" que volta é uma imagem escrita "API KEY REQUIRED" por cima (o nome
 *  do parâmetro é `key`, não `api_key` — a doc oficial usa os dois nomes em
 *  lugares diferentes, só `key` funciona de fato, testado). A chave é
 *  gratuita (5M tiles/mês): carto.com/basemaps/apikey. Fica em `.env.local`
 *  (nunca commitado), não em `.env.production`. */
const CARTO_API_KEY = import.meta.env.VITE_CARTO_API_KEY as string | undefined
const TILE_URL = CARTO_API_KEY
  ? `https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png?key=${CARTO_API_KEY}`
  : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>'

interface Grupo {
  chave: string
  posicao: L.LatLngTuple
  itens: Empreendimento[]
  /** A origem menos precisa do grupo — é ela que o desenho tem que declarar. */
  origem: OrigemCoordenada | null
  precoM2Mediano: number
}

function mediana(valores: number[]): number {
  const ord = [...valores].sort((a, b) => a - b)
  const meio = Math.floor(ord.length / 2)
  return ord.length % 2 ? ord[meio] : (ord[meio - 1] + ord[meio]) / 2
}

function formatarMoeda(valor: number): string {
  return valor.toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 0,
  })
}

/** Reenquadra a cada busca. `bounds` no MapContainer só é lido na montagem —
 *  sem isto, buscar Caucaia deixaria o mapa parado em Fortaleza. */
function AjustarVista({ pontos }: { pontos: L.LatLngTuple[] }) {
  const map = useMap()

  useEffect(() => {
    if (!pontos.length) return
    // Um ponto só — ou uma cidade inteira caída num único centroide — daria
    // bounds degenerados, e o fitBounds iria ao zoom máximo mostrando telhado.
    if (pontos.length === 1) {
      map.setView(pontos[0], 15)
      return
    }
    map.fitBounds(L.latLngBounds(pontos), { padding: [28, 28], maxZoom: 16 })
  }, [map, pontos])

  return null
}

export function Mapa({ empreendimentos, precoM2Medio, semLocalizacao, comCoordenada }: Props) {
  const grupos = useMemo<Grupo[]>(() => {
    const porPosicao = new Map<string, Empreendimento[]>()

    for (const emp of empreendimentos) {
      if (emp.latitude == null || emp.longitude == null) continue
      // 5 casas ≈ 1 metro: junta o que é a mesma posição, separa o que não é.
      const chave = `${emp.latitude.toFixed(5)},${emp.longitude.toFixed(5)}`
      const atual = porPosicao.get(chave)
      if (atual) atual.push(emp)
      else porPosicao.set(chave, [emp])
    }

    return [...porPosicao.entries()].map(([chave, itens]) => {
      const [lat, lng] = chave.split(',').map(Number)
      return {
        chave,
        posicao: [lat, lng] as L.LatLngTuple,
        itens,
        // Se um só do grupo é estimado, o grupo inteiro é declarado estimado:
        // prometer precisão para o conjunto seria mentir sobre parte dele.
        origem: itens.some(i => i.origem_coordenada === 'centroide_bairro')
          ? 'centroide_bairro'
          : itens[0].origem_coordenada,
        precoM2Mediano: mediana(itens.map(i => i.preco_m2)),
      }
    })
  }, [empreendimentos])

  const pontos = useMemo(() => grupos.map(g => g.posicao), [grupos])

  const noMapa = grupos.reduce((n, g) => n + g.itens.length, 0)
  const estimados = grupos.reduce(
    (n, g) => n + g.itens.filter(i => i.origem_coordenada === 'centroide_bairro').length,
    0,
  )
  const exatos = noMapa - estimados

  if (!empreendimentos.length) return null

  // Nenhum ponto: um mapa cinza vazio parece falha de carregamento e não diz
  // nada. Uma frase diz — e, se o portal parou de publicar coordenada, manda
  // olhar o scraper em vez de deixar o sintoma sem explicação.
  if (!grupos.length) {
    return (
      <div className="flex items-start gap-2.5 bg-amber-950/40 border border-amber-800/40 rounded-card px-4 py-3 mb-4 mt-6">
        <AlertTriangle size={15} className="text-amber-400 flex-shrink-0 mt-0.5" />
        <p className="text-sm text-amber-200/90 leading-relaxed">
          <span className="font-semibold">Sem mapa nesta busca.</span>{' '}
          Nenhum dos {empreendimentos.length} anúncios pôde ser posicionado.
          {comCoordenada === 0 && (
            <>
              {' '}Nenhum veio com coordenada dos portais — o formato da página
              pode ter mudado.
            </>
          )}
        </p>
      </div>
    )
  }

  return (
    // `isolate` cria um contexto de empilhamento próprio: os panes do Leaflet
    // são z-index 400 e passariam por cima do painel de histórico (z-40) e do
    // formulário de referencial (z-50), que são fixed.
    <section className="isolate mt-6">
      <div className="mb-3 flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-[11px] font-bold text-mrv-text-dim uppercase tracking-[0.1em]">
          Mapa de anúncios
        </h2>
        <p className="text-[11px] text-mrv-text-dim font-data">
          <span className="text-mrv-text-muted">{noMapa}</span> de {empreendimentos.length} no mapa
          {exatos > 0 && <> · {exatos} no endereço</>}
          {estimados > 0 && <> · {estimados} no centro do bairro</>}
          {semLocalizacao > 0 && <> · {semLocalizacao} sem localização</>}
        </p>
      </div>

      <div className="rounded-card overflow-hidden border border-mrv-border">
        <MapContainer
          // O mapa fica no meio de uma página longa: sequestrar a roda do
          // mouse para dar zoom seria hostil. Zoom pelos botões e duplo clique.
          scrollWheelZoom={false}
          center={grupos[0].posicao}
          zoom={13}
          className="h-[420px] w-full"
        >
          <TileLayer url={TILE_URL} attribution={TILE_ATTR} />
          <AjustarVista pontos={pontos} />

          {/* Estimados primeiro: são os círculos grandes, e desenhados depois
              cobririam os pinos de endereço. */}
          {[...grupos]
            .sort((a, b) => Number(b.origem === 'centroide_bairro') - Number(a.origem === 'centroide_bairro'))
            .map(grupo => {
              const estimado = grupo.origem === 'centroide_bairro'
              const { hex } = faixaPorPreco(grupo.precoM2Mediano, precoM2Medio)
              const n = grupo.itens.length

              return (
                <CircleMarker
                  key={grupo.chave}
                  center={grupo.posicao}
                  radius={n === 1 ? 7 : Math.min(7 + Math.sqrt(n) * 2.6, 20)}
                  pathOptions={{
                    color: hex,
                    weight: estimado ? 2 : 1.5,
                    dashArray: estimado ? '3 4' : undefined,
                    fillColor: hex,
                    fillOpacity: estimado ? 0.12 : 0.75,
                  }}
                >
                  {n > 1 && (
                    // O pino estimado é oco: número escuro sobre ele sumiria
                    // no mapa escuro, e o grupo voltaria a parecer um anúncio
                    // só — justamente o que o contador existe para evitar.
                    <Tooltip
                      permanent
                      direction="center"
                      className={estimado ? 'pin-contador pin-contador-vazado' : 'pin-contador'}
                    >
                      {n}
                    </Tooltip>
                  )}
                  <Popup>
                    <PopupGrupo grupo={grupo} precoM2Medio={precoM2Medio} />
                  </Popup>
                </CircleMarker>
              )
            })}
        </MapContainer>
      </div>
    </section>
  )
}

function PopupGrupo({ grupo, precoM2Medio }: { grupo: Grupo; precoM2Medio: number }) {
  const estimado = grupo.origem === 'centroide_bairro'
  const bairro = grupo.itens[0].bairro
  const n = grupo.itens.length

  return (
    <div className="min-w-[200px]">
      <div className="flex items-center gap-1.5 mb-1.5">
        <MapPin size={12} className="text-mrv-text-muted flex-shrink-0" />
        <span className="font-semibold text-[12px]">
          {n > 1 ? `${n} anúncios` : bairro || 'Anúncio'}
          {n > 1 && bairro && <span className="text-mrv-text-muted"> · {bairro}</span>}
        </span>
      </div>

      {n > 1 && (
        <p className="text-[11px] text-mrv-text-muted mb-1.5 font-data">
          Mediana {formatarMoeda(grupo.precoM2Mediano)}/m²
        </p>
      )}

      {estimado && (
        <p className="flex items-start gap-1 text-[10px] text-amber-300/90 leading-snug mb-2">
          <AlertTriangle size={11} className="flex-shrink-0 mt-px" />
          <span>
            Posição aproximada — centro de {bairro || 'bairro'}, calculada a partir
            dos anúncios geolocalizados da busca. Não é o endereço do imóvel.
          </span>
        </p>
      )}

      {grupo.origem === 'aproximada_portal' && (
        <p className="text-[10px] text-mrv-text-muted leading-snug mb-2">
          Posição aproximada informada pelo portal.
        </p>
      )}

      <ul className="max-h-48 overflow-y-auto divide-y divide-mrv-border/50 -mx-0.5">
        {grupo.itens.map(emp => {
          const pct = desvioPercentual(emp.preco_m2, precoM2Medio)
          const { pctColor } = faixaPorPreco(emp.preco_m2, precoM2Medio)
          return (
            <li key={emp.id} className="py-1.5 px-0.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-data text-[12px]">{formatarMoeda(emp.preco_m2)}/m²</span>
                <span className={`font-data text-[10px] ${pctColor}`}>{rotuloDesvio(pct)}</span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[10px] text-mrv-text-muted">
                <span>
                  {formatarMoeda(emp.preco)} · {emp.area_m2}m²
                  {emp.quartos != null && <> · {emp.quartos}q</>}
                </span>
                <a
                  href={emp.url_anuncio}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-0.5 text-mrv-text-muted hover:text-mrv-text"
                >
                  {PORTAL_LABEL[emp.portal] ?? emp.portal}
                  <ExternalLink size={9} />
                </a>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
