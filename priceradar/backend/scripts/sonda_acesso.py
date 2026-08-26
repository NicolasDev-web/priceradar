"""Sonda de acesso: os portais respondem deste IP?

Existe para responder uma pergunta só, antes de escolher onde hospedar o
PriceRadar: **o acesso gratuito sobrevive fora da máquina do escritório?**

O que torna a coleta gratuita hoje é o `curl-cffi` imitando a assinatura
TLS/JA3 do Chrome — os portais bloqueiam por TLS, não por User-Agent
(`scraper/http.py`). Mas eles também podem pontuar por reputação de ASN, e as
faixas de AWS/GCP/Oracle já entram com nota baixa. Se for esse o caso, a coleta
cai para a ScraperAPI, cujo plano grátis dá 1.000 créditos/mês — cerca de 40
buscas. Isso muda a arquitetura inteira, então é para ser medido, não suposto.

Como usar: rode duas vezes no mesmo dia, com os mesmos argumentos.

    # 1. Na máquina do escritório, para ter a linha de base
    python scripts/sonda_acesso.py --json baseline-local.json

    # 2. Na VM da nuvem
    python scripts/sonda_acesso.py --json sonda-nuvem.json

    # 3. Compare
    python scripts/sonda_acesso.py --comparar baseline-local.json sonda-nuvem.json

Precisa só de `curl-cffi`, `beautifulsoup4` e `lxml` — não de sklearn nem
Playwright. Numa VM nova: `pip install curl-cffi beautifulsoup4 lxml`.

Custa 4 requisições (uma página por portal) e não gasta crédito de proxy: a
sonda usa exclusivamente o nível 1, porque é exatamente o nível 1 que está sob
teste.

O que ele conta são os marcadores estruturais de que cada parser depende, antes
de qualquer filtro de preço ou cidade — é o sinal honesto de "o portal serviu
inventário de verdade":

    vivareal / zap   JSON-LD @type=ItemList          → itemListElement
    chavesnamao      JSON-LD @type=RealEstateListing → offers.itemListElement
    imovelweb        div[data-posting-type=PROPERTY]

Critério de decisão (o mesmo do plano de deploy): os 4 portais em 200, com
contagem dentro de ~20% da linha de base local → dá para hospedar na nuvem.
Qualquer portal caindo para 403 → a coleta fica na rede interna.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.chavesnamao import _build_url as build_chavesnamao_url  # noqa: E402
from scraper.chavesnamao import _sem_acento  # noqa: E402
from scraper.http import _HEADERS, IMPERSONATE, TIMEOUT_SEGUNDOS  # noqa: E402
from scraper.imovelweb import _build_url as build_imovelweb_url  # noqa: E402
from scraper.vivareal import _extrair_estado_cidade, build_vivareal_url  # noqa: E402
from scraper.zapimoveis import build_zapimoveis_url  # noqa: E402

# Tolerância na comparação: abaixo disso a nuvem está vendo menos inventário
# que a máquina local, e a diferença não dá para atribuir a ruído do portal.
_TOLERANCIA = 0.80


def _contar_jsonld(html: str, tipo: str, caminho: tuple[str, ...]) -> int:
    """Conta os itens do bloco JSON-LD de um `@type`, seguindo `caminho` até a lista."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(dados, dict) or dados.get("@type") != tipo:
            continue
        no = dados
        for chave in caminho:
            if not isinstance(no, dict):
                return 0
            no = no.get(chave) or {}
        return len(no) if isinstance(no, list) else 0
    return 0


def _contar_cards_imovelweb(html: str) -> int:
    from bs4 import BeautifulSoup

    return len(BeautifulSoup(html, "lxml").select('div[data-posting-type="PROPERTY"]'))


def _montar_alvos(cidade: str, preco_min: float, preco_max: float, quartos: int | None) -> list[dict]:
    """Uma página por portal, com os mesmos construtores de URL que a busca real usa."""
    # O VivaReal quer o estado por extenso no path (`ceara`); o Zap quer a sigla
    # (`ce`). Trocar um pelo outro devolve 404 — que numa sonda de bloqueio seria
    # lido como portal barrado.
    estado_vr, cidade_vr = _extrair_estado_cidade(cidade)

    partes = cidade.strip().split(",")
    cidade_slug = _sem_acento(partes[0].strip()).lower().replace(" ", "-")
    estado_sigla = partes[1].strip().lower() if len(partes) > 1 else "sp"

    return [
        {
            "portal": "vivareal",
            "url": build_vivareal_url(cidade_vr, estado_vr, preco_min, preco_max, quartos),
            "contar": lambda h: _contar_jsonld(h, "ItemList", ("itemListElement",)),
        },
        {
            "portal": "zapimoveis",
            "url": build_zapimoveis_url(cidade_slug, estado_sigla, preco_min, preco_max, quartos),
            "contar": lambda h: _contar_jsonld(h, "ItemList", ("itemListElement",)),
        },
        {
            "portal": "chavesnamao",
            "url": build_chavesnamao_url(cidade_slug, estado_sigla, preco_min, preco_max, quartos),
            "contar": lambda h: _contar_jsonld(h, "RealEstateListing", ("offers", "itemListElement")),
        },
        {
            "portal": "imovelweb",
            "url": build_imovelweb_url(cidade_slug, estado_sigla, preco_min, preco_max, quartos),
            "contar": _contar_cards_imovelweb,
        },
    ]


def _sondar(alvo: dict) -> dict:
    """Requisição única de nível 1, com a mesma configuração de `scraper/http.py`."""
    from curl_cffi import requests as cr

    resultado = {"portal": alvo["portal"], "url": alvo["url"]}
    inicio = time.monotonic()
    try:
        resp = cr.get(
            alvo["url"],
            impersonate=IMPERSONATE,
            timeout=TIMEOUT_SEGUNDOS,
            headers=_HEADERS,
        )
    except Exception as e:
        resultado.update(status=None, erro=f"{type(e).__name__}: {str(e)[:120]}", kb=0, itens=0)
        resultado["segundos"] = round(time.monotonic() - inicio, 1)
        return resultado

    html = resp.text or ""
    resultado.update(
        status=resp.status_code,
        kb=len(html) // 1024,
        # Só conta se o portal respondeu 200: parsear uma página de bloqueio
        # devolve 0 e mascara a diferença entre "sem inventário" e "barrado".
        itens=alvo["contar"](html) if resp.status_code == 200 else 0,
        segundos=round(time.monotonic() - inicio, 1),
    )
    return resultado


def _imprimir(resultados: list[dict]) -> None:
    print(f"\n{'portal':<14} {'status':>6} {'KB':>6} {'itens':>6} {'seg':>5}")
    print("-" * 42)
    for r in resultados:
        status = r["status"] if r["status"] is not None else "erro"
        print(f"{r['portal']:<14} {str(status):>6} {r['kb']:>6} {r['itens']:>6} {r['segundos']:>5}")
        if r.get("erro"):
            print(f"{'':<14} {r['erro']}")


def _veredito(resultados: list[dict]) -> bool:
    """True quando todos os portais responderam 200 com inventário."""
    ok = [r for r in resultados if r["status"] == 200 and r["itens"] > 0]
    bloqueados = [r for r in resultados if r["status"] in (403, 401, 429)]

    print(f"\n{len(ok)}/{len(resultados)} portais com inventário.")
    if bloqueados:
        nomes = ", ".join("{} ({})".format(r["portal"], r["status"]) for r in bloqueados)
        print(f"Barrados: {nomes}")
    return len(ok) == len(resultados)


def _comparar(caminho_base: str, caminho_novo: str) -> bool:
    base = {r["portal"]: r for r in json.loads(Path(caminho_base).read_text(encoding="utf-8"))["resultados"]}
    novo = {r["portal"]: r for r in json.loads(Path(caminho_novo).read_text(encoding="utf-8"))["resultados"]}

    print(f"\n{'portal':<14} {'base':>12} {'novo':>12} {'razão':>8}")
    print("-" * 50)
    aprovado = True
    for portal, r_base in base.items():
        r_novo = novo.get(portal)
        if r_novo is None:
            print(f"{portal:<14} {'ausente na segunda medição':>34}")
            aprovado = False
            continue
        razao = r_novo["itens"] / r_base["itens"] if r_base["itens"] else 0.0
        marca = "ok" if razao >= _TOLERANCIA else "CAIU"
        if razao < _TOLERANCIA:
            aprovado = False
        print(
            f"{portal:<14} {str(r_base['status']) + '/' + str(r_base['itens']):>12}"
            f" {str(r_novo['status']) + '/' + str(r_novo['itens']):>12} {razao:>7.0%} {marca}"
        )

    print(
        "\nVeredito: dá para hospedar na nuvem."
        if aprovado
        else f"\nVeredito: o segundo IP vê menos inventário (corte em {_TOLERANCIA:.0%}). A coleta fica na rede interna."
    )
    return aprovado


def main() -> int:
    p = argparse.ArgumentParser(description="Mede se os portais respondem deste IP.")
    p.add_argument("--cidade", default="Fortaleza, CE")
    p.add_argument("--preco-min", type=float, default=280000)
    p.add_argument("--preco-max", type=float, default=500000)
    p.add_argument("--quartos", type=int, default=2)
    p.add_argument("--json", metavar="ARQUIVO", help="grava o resultado para comparação posterior")
    p.add_argument("--comparar", nargs=2, metavar=("BASE", "NOVO"), help="compara dois arquivos --json e sai")
    args = p.parse_args()

    if args.comparar:
        return 0 if _comparar(*args.comparar) else 1

    print(f"Sondando de {platform.node()} ({platform.system()}) — impersonate={IMPERSONATE}")
    print(f"Recorte: {args.cidade}, R$ {args.preco_min:,.0f}-{args.preco_max:,.0f}, {args.quartos} quartos")

    alvos = _montar_alvos(args.cidade, args.preco_min, args.preco_max, args.quartos)
    resultados = [_sondar(a) for a in alvos]

    _imprimir(resultados)
    aprovado = _veredito(resultados)

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "maquina": platform.node(),
                    "sistema": platform.system(),
                    "impersonate": IMPERSONATE,
                    "cidade": args.cidade,
                    "preco_min": args.preco_min,
                    "preco_max": args.preco_max,
                    "quartos": args.quartos,
                    "resultados": resultados,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Gravado em {args.json}")

    return 0 if aprovado else 1


if __name__ == "__main__":
    raise SystemExit(main())
