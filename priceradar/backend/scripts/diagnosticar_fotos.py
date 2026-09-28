"""Diagnóstico de volume e fotos por portal — a F1.1 e a F4.1 do PLANO_MELHORIAS.md.

Roda cada scraper UMA vez na busca de referência (Fortaleza, CE — R$ 280k a
500k — 2 quartos) e responde, por portal:

- quantos anúncios vieram (linha de base de volume);
- quantos vieram com foto e quantas fotos em média;
- se a primeira foto abre SEM cabeçalho Referer, como o navegador vai pedir
  (`referrerPolicy="no-referrer"` no card). Se não abrir, o card mostra a
  imagem genérica — e aí é preciso o proxy de imagem (F1.9 do plano).

Foi escrito num ambiente sem acesso aos portais: a extração de fotos está
ligada em todos os scrapers, mas só este script confirma que ela acha foto de
verdade. Rode na máquina com acesso:

    cd priceradar\\backend
    venv\\Scripts\\python.exe scripts\\diagnosticar_fotos.py
    venv\\Scripts\\python.exe scripts\\diagnosticar_fotos.py --portais vivareal chavesnamao
    venv\\Scripts\\python.exe scripts\\diagnosticar_fotos.py --json data\\diagnostico-fotos.json

Desde a F5.2 ele também mede a COLETA de cada portal:

- status HTTP e tamanho da resposta da primeira página — capturados do caminho
  que o scraper já percorre (observador em `scraper/http.py`, gancho no
  `httpx.AsyncClient` para ChavesNaMão/QuintoAndar e no Playwright), sem
  nenhuma requisição extra;
- classificação: ok / bloqueado / parser quebrado / sem inventário / erro;
- páginas lidas × teto e se a última página lida ainda trouxe anúncio novo
  (`scraper/paginacao.py::ESTATISTICAS`) → recomendação de teto.

A medição só vale na rede do PC que serve o link oficial: rede corporativa com
inspeção TLS, ou uma sessão na nuvem, gera 403 que não existe em produção.

Custa o mesmo que uma busca normal (as mesmas requisições, com o mesmo
espaçamento de cada scraper), mais um pedido de imagem por portal.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import httpx  # noqa: E402

from scraper import http as scraper_http  # noqa: E402
from scraper import paginacao  # noqa: E402
from scraper.chavesnamao import scrape_chavesnamao  # noqa: E402
from scraper.imovelweb import scrape_imovelweb  # noqa: E402
from scraper.mercadolivre import scrape_mercadolivre  # noqa: E402
from scraper.netimoveisagent import scrape_netimoveis  # noqa: E402
from scraper.olximoveis import scrape_olximoveis  # noqa: E402
from scraper.quintoandar import scrape_quintoandar  # noqa: E402
from scraper.vivareal import scrape_vivareal  # noqa: E402
from scraper.zapimoveis import scrape_zapimoveis  # noqa: E402
from services.search import extrair_cidade_estado  # noqa: E402

CIDADE = "Fortaleza, CE"
NOME, UF = extrair_cidade_estado(CIDADE)
PRECO_MIN, PRECO_MAX, QUARTOS = 280_000, 500_000, 2

# Mesmas assinaturas que services/search.py usa.
PORTAIS = {
    "vivareal": lambda: scrape_vivareal(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "zapimoveis": lambda: scrape_zapimoveis(NOME, UF, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "chavesnamao": lambda: scrape_chavesnamao(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "imovelweb": lambda: scrape_imovelweb(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "quintoandar": lambda: scrape_quintoandar(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "olx": lambda: scrape_olximoveis(NOME, UF, PRECO_MIN, PRECO_MAX, QUARTOS),
    "netimoveis": lambda: scrape_netimoveis(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
    "mercadolivre": lambda: scrape_mercadolivre(CIDADE, PRECO_MIN, PRECO_MAX, QUARTOS, None),
}


async def _foto_abre(url: str) -> str:
    """'ok', 'bloqueada (403)', 'nao_e_imagem' ou o erro de rede."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return f"bloqueada ({r.status_code})"
        if not r.headers.get("content-type", "").startswith("image/"):
            return "nao_e_imagem"
        return "ok"
    except httpx.HTTPError as e:
        return type(e).__name__


# ── Captura das respostas HTTP (sem requisição extra) ────────────────────────

# Rótulos da classificação — exatamente os da definição do agente
# medicao-portais, para o BASELINE.json comparar medições entre si.
OK, BLOQUEADO, PARSER_QUEBRADO, SEM_INVENTARIO, ERRO = (
    "ok", "bloqueado", "parser quebrado", "sem inventário", "erro")

# Abaixo disso o HTML não tem como conter uma listagem de 20+ anúncios; a
# página de "nenhum resultado" dos portais fica bem menor. Empírico: ajustar
# com a primeira medição real (F5.1) se algum portal cair do lado errado.
LIMIAR_HTML_GRANDE = 50 * 1024

# Página de desafio anti-bot devolve 200 às vezes — o status sozinho engana.
_MARCADORES_DESAFIO = (
    "cf-chl", "challenge-platform", "/cdn-cgi/challenge", "just a moment",
    "attention required", "captcha", "px-captcha", "perimeterx", "access denied",
)
# Sinais de que a página TEM uma listagem estruturada (JSON-LD, Next.js,
# estado inicial) — se tem isso, é grande e saiu 0 anúncio, o parser quebrou.
_MARCADORES_LISTAGEM = (
    "application/ld+json", "__next_data__", "realestatelisting", "itemlistelement",
    "initialstate", "__initial_state__", "\"listings\"", "\"results\"",
)

# Parâmetros que podem carregar segredo em alguma URL capturada. As URLs dos
# portais não os têm, mas a regra é nunca imprimir chave — então se limpa.
_PARAMS_SECRETOS = {"api_key", "apikey", "key", "token", "access_token"}


def _url_segura(url: str) -> str:
    try:
        partes = urlsplit(str(url))
        query = [(k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True)
                 if k.lower() not in _PARAMS_SECRETOS]
        return urlunsplit(partes._replace(query=urlencode(query)))
    except ValueError:
        return "?"


class ColetorHttp:
    """
    Junta as respostas que o scraper recebeu enquanto roda um portal.

    Cada evento guarda só números e sinais (status, bytes, desafio?, tem
    listagem?) — o corpo é inspecionado na chegada e descartado, para não
    inflar o JSON nem gravar HTML de terceiros.
    """

    def __init__(self) -> None:
        self.eventos: list[dict] = []

    def registrar(self, evento: dict) -> None:
        corpo = (evento.pop("corpo", "") or "")[:400_000].lower()
        evento["url"] = _url_segura(evento.get("url", ""))
        evento["desafio"] = any(m in corpo for m in _MARCADORES_DESAFIO)
        evento["marcador_listagem"] = any(m in corpo for m in _MARCADORES_LISTAGEM)
        self.eventos.append(evento)

    def primeira_pagina(self) -> dict | None:
        """
        A resposta FINAL da primeira URL pedida.

        "Primeira" pela hora de entrada (`inicio`): as páginas de um lote saem
        em paralelo, mas a p1 é a primeira a entrar na camada HTTP. "Final"
        pela hora de término: se o direto deu 403 e a ScraperAPI deu 200, o
        que o scraper usou foi o 200 — e as tentativas ficam listadas.
        """
        if not self.eventos:
            return None
        url = min(self.eventos, key=lambda e: e["inicio"])["url"]
        da_url = sorted((e for e in self.eventos if e["url"] == url), key=lambda e: e["fim"])
        final = da_url[-1]
        return {
            "url": url,
            "status": final["status"],
            "bytes": final["bytes"],
            "nivel": final["nivel"],
            "desafio": final["desafio"],
            "marcador_listagem": final["marcador_listagem"],
            "erro": final.get("erro"),
            "tentativas": [f"{e['nivel']}:{e['status'] if e['status'] is not None else e.get('erro') or 'sem resposta'}"
                           for e in da_url],
        }


@contextlib.contextmanager
def _capturar_http(coletor: ColetorHttp):
    """
    Liga a captura só durante o scraper de um portal e desliga ao sair.

    Três caminhos, todos observados sem mudar o que o scraper faz:
    1. `scraper/http.py` (curl-cffi e ScraperAPI) avisa o observador;
    2. ChavesNaMão e QuintoAndar usam `httpx.AsyncClient` direto — o `send`
       é embrulhado; a ScraperAPI (que também é httpx) é pulada aqui porque o
       item 1 já a registra, com a URL do portal no lugar da URL com chave;
    3. Playwright (Netimóveis, Mercado Livre e o último recurso dos outros) —
       os nomes importados em cada módulo de scraper são embrulhados. Não há
       status HTTP ali: HTML devolvido conta como 200, None como sem resposta.
    """
    scraper_http.adicionar_observador(coletor.registrar)

    send_original = httpx.AsyncClient.send

    async def send_observado(self, request, *args, **kwargs):
        if (request.url.host or "").endswith("scraperapi.com"):
            return await send_original(self, request, *args, **kwargs)
        inicio = time.perf_counter()
        try:
            resp = await send_original(self, request, *args, **kwargs)
        except Exception as e:
            coletor.registrar({"portal": None, "url": str(request.url), "nivel": "httpx", "status": None,
                               "bytes": 0, "corpo": "", "erro": type(e).__name__,
                               "inicio": inicio, "fim": time.perf_counter()})
            raise
        try:
            corpo = resp.content  # send() sem stream já leu o corpo
            coletor.registrar({"portal": None, "url": str(request.url), "nivel": "httpx",
                               "status": resp.status_code, "bytes": len(corpo),
                               "corpo": corpo.decode("utf-8", errors="replace"), "erro": None,
                               "inicio": inicio, "fim": time.perf_counter()})
        except Exception:  # noqa: BLE001 — resposta em stream etc.: não medir, não quebrar
            pass
        return resp

    embrulhados: list[tuple[object, str, object]] = []

    def _embrulhar_playwright(original):
        async def observado(*args, **kwargs):
            url = args[0] if args else kwargs.get("url") or kwargs.get("url_pagina", "")
            inicio = time.perf_counter()
            resultado = await original(*args, **kwargs)
            if isinstance(resultado, str):
                corpo = resultado
            elif resultado:
                corpo = json.dumps(resultado, default=str, ensure_ascii=False)
            else:
                corpo = ""
            coletor.registrar({"portal": None, "url": str(url), "nivel": "playwright",
                               "status": 200 if corpo else None,
                               "bytes": len(corpo.encode("utf-8", errors="replace")), "corpo": corpo,
                               "erro": None if corpo else "sem conteúdo",
                               "inicio": inicio, "fim": time.perf_counter()})
            return resultado
        return observado

    for nome_mod, mod in list(sys.modules.items()):
        if not nome_mod.startswith("scraper.") or mod is None:
            continue
        for attr in ("buscar_html_playwright", "interceptar_api_playwright"):
            original = getattr(mod, attr, None)
            if callable(original):
                embrulhados.append((mod, attr, original))
                setattr(mod, attr, _embrulhar_playwright(original))

    httpx.AsyncClient.send = send_observado
    try:
        yield coletor
    finally:
        httpx.AsyncClient.send = send_original
        for mod, attr, original in embrulhados:
            setattr(mod, attr, original)
        scraper_http.remover_observador(coletor.registrar)


# ── Classificação e recomendação ─────────────────────────────────────────────

def classificar(anuncios: int, erro: str | None, primeira: dict | None) -> str:
    """
    Rótulos da definição do agente medicao-portais:

    - erro: exceção no scraper (os scrapers engolem a maioria; só o que escapa);
    - ok: trouxe anúncio — mesmo que alguma página tenha falhado;
    - bloqueado: 403/429, página de desafio, ou nenhuma resposta;
    - sem inventário: 200 com HTML pequeno ou sem marcador de listagem
      (e 404/410: a URL de busca não existe para aquela cidade);
    - parser quebrado: 200 com HTML grande e com listagem, mas 0 anúncios.
    """
    if erro:
        return ERRO
    if anuncios > 0:
        return OK
    if primeira is None or primeira["status"] is None:
        return BLOQUEADO
    status = primeira["status"]
    if status in (404, 410):
        return SEM_INVENTARIO
    if status != 200 or primeira["desafio"]:
        # Outros não-200 (5xx do Cloudflare, 401...) são, na prática, recusa.
        return BLOQUEADO
    if primeira["bytes"] >= LIMIAR_HTML_GRANDE and primeira["marcador_listagem"]:
        return PARSER_QUEBRADO
    return SEM_INVENTARIO


def recomendar_teto(pag: dict | None) -> str | None:
    """
    'subir teto' só com as duas condições: leu até o teto E a última página
    ainda trouxe anúncio novo — senão o inventário acabou antes e subir o
    teto só adicionaria requisição (regra do plano: medir antes de subir).
    """
    if not pag:
        return None  # portal sem paginação (OLX, Netimóveis, Mercado Livre)
    if pag["parou_no_teto"] and pag["ultima_pagina_trouxe_novos"]:
        return "subir teto"
    return "manter teto"


async def _executar_scraper(portal: str, fabrica) -> tuple[list[dict], str | None, dict | None, dict | None]:
    """Roda o scraper com a captura ligada; devolve itens, erro, 1ª página, paginação."""
    paginacao.ESTATISTICAS.clear()  # um portal por vez: o que aparecer é dele
    coletor = ColetorHttp()
    with _capturar_http(coletor):
        try:
            itens = await fabrica()
            erro = None
        except Exception as e:  # o diagnóstico nunca para por causa de um portal
            itens, erro = [], f"{type(e).__name__}: {str(e)[:200]}"
    # Cada scraper chama `paginar` uma vez; se um dia chamar mais, vale a última.
    pag = list(paginacao.ESTATISTICAS.values())[-1] if paginacao.ESTATISTICAS else None
    if pag:
        pag = {k: v for k, v in pag.items() if k != "novos_por_pagina"} | {
            "novos_por_pagina": {str(k): v for k, v in pag["novos_por_pagina"].items()}}
    return itens or [], erro, coletor.primeira_pagina(), pag


async def diagnosticar(portal: str, portais: dict | None = None) -> dict:
    inicio = time.time()
    itens, erro, primeira, pag = await _executar_scraper(portal, (portais or PORTAIS)[portal])
    com_foto = [i for i in itens if i.get("fotos")]
    amostra = com_foto[0]["fotos"][0] if com_foto else None
    classificacao = classificar(len(itens), erro, primeira)
    r = {
        "portal": portal,
        "classificacao": classificacao,
        "anuncios": len(itens),
        "http_status": primeira["status"] if primeira else None,
        "http_bytes": primeira["bytes"] if primeira else None,
        "primeira_pagina": primeira,
        "paginacao": pag,
        "recomendacao_teto": recomendar_teto(pag) if classificacao == OK else None,
        "com_foto": len(com_foto),
        "media_fotos": round(sum(len(i["fotos"]) for i in com_foto) / len(com_foto), 1) if com_foto else 0,
        "amostra_foto": amostra,
        "foto_abre_sem_referer": await _foto_abre(amostra) if amostra else None,
        "tempo_s": round(time.time() - inicio, 1),
        "erro": erro,
    }
    r["veredito"] = _veredito(r)
    return r


def _veredito(r: dict) -> str:
    """Uma frase que diz o que fazer — o consumo é humano (e o F5.3)."""
    c = r.get("classificacao")
    st = r.get("http_status")
    if c == ERRO:
        return "ERRO no scraper — ver a exceção abaixo e corrigir antes de medir de novo"
    if c == BLOQUEADO:
        erro_rede = (r.get("primeira_pagina") or {}).get("erro")
        motivo = ((f"sem resposta: {erro_rede}" if erro_rede else "sem resposta") if st is None else
                  "página de desafio" if (r.get("primeira_pagina") or {}).get("desafio") else f"HTTP {st}")
        return f"bloqueado ({motivo}) — não forçar; confirmar na rede do link oficial"
    if c == PARSER_QUEBRADO:
        return f"parser quebrado (HTML de {(r.get('http_bytes') or 0) // 1024}KB, 0 anúncios) — consertar extração (diagnosticar-scraper)"
    if c == SEM_INVENTARIO:
        return "sem inventário — conferir a URL de busca da cidade/filtros"
    avisos = []
    if r.get("recomendacao_teto") == "subir teto":
        pag = r["paginacao"]
        avisos.append(f"subir teto (leu {pag['paginas_lidas']}/{pag['teto']} e a última ainda trouxe novos)")
    if not r["com_foto"]:
        avisos.append("sem foto — achar onde o portal põe a imagem e ajustar o scraper")
    elif r["foto_abre_sem_referer"] != "ok":
        avisos.append("foto não abre direto — precisa do proxy de imagem (F1.9)")
    elif r["com_foto"] < 0.8 * r["anuncios"]:
        avisos.append("foto em parte dos anúncios — conferir")
    return "; ".join(avisos) if avisos else "OK"


def montar_relatorio(resultados: list[dict]) -> dict:
    """Formato do --json: metadados da medição + um bloco por portal."""
    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "busca": {"cidade": CIDADE, "preco_min": PRECO_MIN, "preco_max": PRECO_MAX, "quartos": QUARTOS},
        "aviso_rede": ("Só vale medido na rede do PC que serve o link oficial; rede corporativa "
                       "ou nuvem geram 403 que não existe em produção."),
        "portais": resultados,
    }


def _fmt_paginas(pag: dict | None) -> str:
    if not pag:
        return "-"
    return f"{pag['paginas_lidas']}/{pag['teto']}{'+' if pag['ultima_pagina_trouxe_novos'] else ''}"


def imprimir_tabela(resultados: list[dict]) -> None:
    print(f"\nBusca de referência: {CIDADE} — R$ {PRECO_MIN:,} a {PRECO_MAX:,} — {QUARTOS} quartos\n")
    print(f"{'portal':<13}{'classificação':<16}{'anúnc.':>7}{'HTTP':>6}{'KB':>7}{'págs':>8}"
          f"{'c/ foto':>8}{'média':>6}  {'foto abre?':<16} veredito")
    for r in resultados:
        kb = "-" if r["http_bytes"] is None else r["http_bytes"] // 1024
        print(f"{r['portal']:<13}{r['classificacao']:<16}{r['anuncios']:>7}{str(r['http_status'] or '-'):>6}"
              f"{kb:>7}{_fmt_paginas(r['paginacao']):>8}{r['com_foto']:>8}{r['media_fotos']:>6}  "
              f"{str(r['foto_abre_sem_referer'] or '-'):<16} {r['veredito']}")
        if r["primeira_pagina"] and len(r["primeira_pagina"]["tentativas"]) > 1:
            print(f"{'':<13}tentativas na 1ª página: {' → '.join(r['primeira_pagina']['tentativas'])}")
        if r["erro"]:
            print(f"{'':<13}{r['erro']}")
    print("\npágs = lidas/teto; '+' = a última página lida ainda trouxe anúncio novo.")
    print("Medição só vale na rede do PC que serve o link oficial.")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--portais", nargs="*", default=list(PORTAIS), choices=list(PORTAIS))
    ap.add_argument("--json", help="grava o resultado neste arquivo")
    args = ap.parse_args()

    # Um portal por vez, de propósito: em paralelo seria outra carga sobre os
    # portais que não a de uma busca normal — e a captura HTTP e as
    # estatísticas de paginação são por portal, não misturam.
    resultados = [await diagnosticar(p) for p in args.portais]

    imprimir_tabela(resultados)

    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(montar_relatorio(resultados), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGravado em {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
