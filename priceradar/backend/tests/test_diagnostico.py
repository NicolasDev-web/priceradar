"""Diagnóstico da coleta por portal (F5.2) — sem rede.

Os "scrapers" daqui são funções falsas que percorrem o mesmo caminho dos
reais: avisam `scraper/http.py` como o curl-cffi avisaria, usam
`httpx.AsyncClient` com transporte falso (como ChavesNaMão/QuintoAndar) e
paginam com `scraper/paginacao.py::paginar`.
"""
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from scraper import http as scraper_http  # noqa: E402
from scraper import paginacao  # noqa: E402
from scraper.paginacao import paginar  # noqa: E402

_spec = importlib.util.spec_from_file_location("diagnosticar_fotos", RAIZ / "scripts" / "diagnosticar_fotos.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

HTML_GRANDE = '<script type="application/ld+json">{"@type":"RealEstateListing"}</script>' + "x" * 80_000
HTML_PEQUENO = "<html><body>Nenhum imóvel encontrado</body></html>"
HTML_DESAFIO = "<html><title>Just a moment...</title>" + "y" * 80_000


def _evento(url, status, corpo="", nivel="direto", erro=None, inicio=None):
    t = time.perf_counter() if inicio is None else inicio
    return {"portal": "X", "url": url, "nivel": nivel, "status": status,
            "bytes": len(corpo.encode()), "corpo": corpo, "erro": erro, "inicio": t, "fim": t + 0.01}


def _anuncios(pagina, n=2, com_foto=False):
    return [{"url_anuncio": f"https://portal/imovel/{pagina}-{i}",
             "fotos": [f"https://img/{pagina}-{i}.jpg"] if com_foto else []} for i in range(n)]


# ── Classificação ────────────────────────────────────────────────────────────

def _primeira(status, bytes_=0, desafio=False, listagem=False):
    return {"status": status, "bytes": bytes_, "desafio": desafio, "marcador_listagem": listagem}


@pytest.mark.parametrize("anuncios, erro, primeira, esperado", [
    (0, "RuntimeError: boom", None, "erro"),
    (5, None, _primeira(200, 90_000, listagem=True), "ok"),
    (5, None, None, "ok"),  # Playwright/sem captura, mas trouxe anúncio
    (0, None, None, "bloqueado"),  # nenhuma resposta
    (0, None, _primeira(None), "bloqueado"),
    (0, None, _primeira(403), "bloqueado"),
    (0, None, _primeira(429), "bloqueado"),
    (0, None, _primeira(200, 90_000, desafio=True, listagem=True), "bloqueado"),
    (0, None, _primeira(200, 90_000, listagem=True), "parser quebrado"),
    (0, None, _primeira(200, 90_000, listagem=False), "sem inventário"),
    (0, None, _primeira(200, 2_000, listagem=True), "sem inventário"),
    (0, None, _primeira(404), "sem inventário"),
])
def test_classificacao(anuncios, erro, primeira, esperado):
    assert diag.classificar(anuncios, erro, primeira) == esperado


def test_primeira_pagina_e_a_primeira_pedida_com_a_resposta_final():
    c = diag.ColetorHttp()
    t = time.perf_counter()
    # p2 terminou antes, mas a p1 entrou primeiro; na p1 o direto deu 403 e a
    # ScraperAPI salvou com 200 — o que vale é o 200.
    c.registrar(_evento("https://p/busca?pg=2", 200, HTML_GRANDE, inicio=t + 0.001))
    c.registrar(_evento("https://p/busca", 403, HTML_PEQUENO, inicio=t))
    c.registrar(_evento("https://p/busca", 200, HTML_GRANDE, nivel="scraperapi", inicio=t + 0.5))
    p = c.primeira_pagina()
    assert p["url"] == "https://p/busca"
    assert p["status"] == 200 and p["nivel"] == "scraperapi"
    assert p["tentativas"] == ["direto:403", "scraperapi:200"]
    assert p["marcador_listagem"] and not p["desafio"]
    assert "corpo" not in c.eventos[0]  # HTML não fica guardado


def test_url_capturada_nunca_leva_chave():
    c = diag.ColetorHttp()
    c.registrar(_evento("https://api.x.com/?api_key=SEGREDO&url=https%3A%2F%2Fp", 200))
    assert "SEGREDO" not in c.eventos[0]["url"]


# ── Estatísticas da paginação → recomendação de teto ─────────────────────────

def _paginar(inventario, teto, nome="Falso"):
    async def buscar(p):
        return inventario.get(p, [])
    return asyncio.run(paginar(buscar, teto, nome, tamanho_lote=3))


def test_parou_no_teto_com_a_ultima_trazendo_novos_recomenda_subir():
    _paginar({p: _anuncios(p) for p in range(1, 10)}, 6, "Cheio")
    est = paginacao.ESTATISTICAS["Cheio"]
    assert est["paginas_lidas"] == 6 and est["teto"] == 6
    assert est["parou_no_teto"] and est["ultima_pagina_trouxe_novos"]
    assert est["novos_por_pagina"] == {p: 2 for p in range(1, 7)}
    assert diag.recomendar_teto(est) == "subir teto"


def test_inventario_curto_recomenda_manter():
    _paginar({1: _anuncios(1), 2: _anuncios(2)}, 12, "Curto")
    est = paginacao.ESTATISTICAS["Curto"]
    assert est["paginas_lidas"] == 6 and not est["parou_no_teto"]
    assert not est["ultima_pagina_trouxe_novos"]
    assert diag.recomendar_teto(est) == "manter teto"


def test_no_teto_mas_ultima_pagina_so_repetida_mantem():
    repetida = _anuncios(1)
    _paginar({1: repetida, 2: _anuncios(2), 3: repetida}, 3, "Repete")
    est = paginacao.ESTATISTICAS["Repete"]
    assert est["parou_no_teto"] and not est["ultima_pagina_trouxe_novos"]
    assert diag.recomendar_teto(est) == "manter teto"


def test_portal_sem_paginacao_nao_tem_recomendacao():
    assert diag.recomendar_teto(None) is None


# ── Ponta a ponta com scrapers falsos ────────────────────────────────────────

async def _scraper_via_http_py():
    """Imita VivaReal/Zap: p1 passa por http.py (curl-cffi) e volta 200 grande, 0 válidos."""
    async def pagina(p):
        scraper_http._notificar(**_evento(f"https://portal/busca?p={p}", 200, HTML_GRANDE))
        return []
    return await paginar(pagina, 2, "ViaHttp", tamanho_lote=3)


async def _scraper_via_httpx(status):
    """Imita ChavesNaMão/QuintoAndar: httpx.AsyncClient direto."""
    transporte = httpx.MockTransport(lambda req: httpx.Response(status, text=HTML_PEQUENO))

    async def pagina(p):
        async with httpx.AsyncClient(transport=transporte) as c:
            r = await c.get(f"https://portal2/busca?pg={p}")
        return _anuncios(p, com_foto=True) if r.status_code == 200 else []
    return await paginar(pagina, 3, "ViaHttpx", tamanho_lote=3)


async def _scraper_que_explode():
    raise RuntimeError("seletor sumiu")


@pytest.fixture
def portais_falsos(monkeypatch):
    async def foto_ok(url):
        return "ok"
    monkeypatch.setattr(diag, "_foto_abre", foto_ok)
    falsos = {
        "viahttp": _scraper_via_http_py,
        "bloqueado": lambda: _scraper_via_httpx(403),
        "cheio": lambda: _scraper_via_httpx(200),
        "explode": _scraper_que_explode,
    }
    monkeypatch.setattr(diag, "PORTAIS", falsos)
    return falsos


def test_parser_quebrado_via_http_py(portais_falsos):
    r = asyncio.run(diag.diagnosticar("viahttp"))
    assert r["classificacao"] == "parser quebrado"
    assert r["http_status"] == 200 and r["http_bytes"] > diag.LIMIAR_HTML_GRANDE
    assert r["paginacao"]["paginas_lidas"] == 2 and r["paginacao"]["teto"] == 2
    assert "parser quebrado" in r["veredito"]
    # a captura foi desligada ao sair
    assert not scraper_http._observadores


def test_bloqueado_via_httpx_e_send_restaurado(portais_falsos):
    send_antes = httpx.AsyncClient.send
    r = asyncio.run(diag.diagnosticar("bloqueado"))
    assert httpx.AsyncClient.send is send_antes
    assert r["classificacao"] == "bloqueado"
    assert r["http_status"] == 403
    assert r["primeira_pagina"]["url"] == "https://portal2/busca?pg=1"
    assert r["recomendacao_teto"] is None
    assert "HTTP 403" in r["veredito"]


def test_ok_no_teto_recomenda_subir(portais_falsos):
    r = asyncio.run(diag.diagnosticar("cheio"))
    assert r["classificacao"] == "ok" and r["anuncios"] == 6
    assert r["recomendacao_teto"] == "subir teto"
    assert r["foto_abre_sem_referer"] == "ok"
    assert r["veredito"].startswith("subir teto (leu 3/3")


def test_excecao_vira_erro(portais_falsos):
    r = asyncio.run(diag.diagnosticar("explode"))
    assert r["classificacao"] == "erro"
    assert "RuntimeError" in r["erro"]
    assert r["veredito"].startswith("ERRO")


def test_formato_do_json(portais_falsos, monkeypatch, tmp_path):
    destino = tmp_path / "sub" / "diag.json"
    monkeypatch.setattr(sys, "argv", ["x", "--portais", "viahttp", "bloqueado", "cheio", "explode",
                                      "--json", str(destino)])
    asyncio.run(diag.main())
    dados = json.loads(destino.read_text(encoding="utf-8"))
    assert set(dados) == {"gerado_em", "busca", "aviso_rede", "portais"}
    assert [p["portal"] for p in dados["portais"]] == ["viahttp", "bloqueado", "cheio", "explode"]
    campos = {"portal", "classificacao", "anuncios", "http_status", "http_bytes", "primeira_pagina",
              "paginacao", "recomendacao_teto", "com_foto", "media_fotos", "amostra_foto",
              "foto_abre_sem_referer", "tempo_s", "erro", "veredito"}
    for p in dados["portais"]:
        assert set(p) == campos
        assert p["classificacao"] in {"ok", "bloqueado", "parser quebrado", "sem inventário", "erro"}
    cheio = dados["portais"][2]
    assert set(cheio["paginacao"]) >= {"paginas_lidas", "teto", "parou_no_teto",
                                       "ultima_pagina_trouxe_novos", "novos_por_pagina"}
    # O HTML capturado não vai para o JSON — só números e sinais.
    assert all("corpo" not in p["primeira_pagina"] for p in dados["portais"] if p["primeira_pagina"])
    assert "Nenhum imóvel encontrado" not in json.dumps(dados, ensure_ascii=False)


# ── http.py: o observador é aditivo ─────────────────────────────────────────

class _RespFalsa:
    status_code = 200
    text = HTML_GRANDE


class _SessaoFalsa:
    def get(self, *a, **k):
        return _RespFalsa()


def test_http_direto_notifica_sem_mudar_retorno(monkeypatch):
    monkeypatch.setattr(scraper_http, "_sessao_do_host", lambda url, cr: _SessaoFalsa())

    async def sem_espera():
        return None
    monkeypatch.setattr(scraper_http, "_aguardar_jitter", sem_espera)

    # Sem observador: comportamento de sempre.
    assert asyncio.run(scraper_http.buscar_html_direto("https://p/a", "P")) == HTML_GRANDE

    eventos = []
    scraper_http.adicionar_observador(eventos.append)
    # Observador com defeito não derruba a busca.
    scraper_http.adicionar_observador(lambda e: 1 / 0)
    try:
        assert asyncio.run(scraper_http.buscar_html_direto("https://p/a", "P")) == HTML_GRANDE
    finally:
        scraper_http._observadores.clear()
    assert len(eventos) == 1
    assert eventos[0]["status"] == 200 and eventos[0]["nivel"] == "direto"
    assert eventos[0]["bytes"] == len(HTML_GRANDE)


def test_scraperapi_notifica_url_do_portal_sem_chave(monkeypatch):
    monkeypatch.setattr(scraper_http, "SCRAPERAPI_KEY", "CHAVE-SECRETA")
    transporte = httpx.MockTransport(lambda req: httpx.Response(403, text="negado"))
    cliente_real = httpx.AsyncClient
    monkeypatch.setattr(scraper_http.httpx, "AsyncClient",
                        lambda **k: cliente_real(transport=transporte, **k))
    eventos = []
    scraper_http.adicionar_observador(eventos.append)
    try:
        assert asyncio.run(scraper_http.buscar_html_scraperapi("https://p/a", "P")) is None
    finally:
        scraper_http._observadores.clear()
    assert eventos and eventos[0]["url"] == "https://p/a" and eventos[0]["status"] == 403
    assert "CHAVE-SECRETA" not in json.dumps(eventos)


def test_log_de_erro_da_scraperapi_nao_vaza_a_chave(monkeypatch):
    from scraper import http as http_mod
    monkeypatch.setattr(http_mod, "SCRAPERAPI_KEY", "chave-secreta-123")
    msg = "ConnectError for url 'https://api.scraperapi.com/?api_key=chave-secreta-123&url=https%3A%2F%2Fx'"
    limpo = http_mod._sem_chave(msg)
    assert "chave-secreta-123" not in limpo and "api_key=***" in limpo
