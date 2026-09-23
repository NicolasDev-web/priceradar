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

Custa o mesmo que uma busca normal (as mesmas requisições, com o mesmo
espaçamento de cada scraper), mais um pedido de imagem por portal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import httpx  # noqa: E402

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


async def diagnosticar(portal: str) -> dict:
    inicio = time.time()
    try:
        itens = await PORTAIS[portal]()
        erro = None
    except Exception as e:  # o diagnóstico nunca para por causa de um portal
        itens, erro = [], f"{type(e).__name__}: {e}"
    com_foto = [i for i in itens if i.get("fotos")]
    amostra = com_foto[0]["fotos"][0] if com_foto else None
    return {
        "portal": portal,
        "anuncios": len(itens),
        "com_foto": len(com_foto),
        "media_fotos": round(sum(len(i["fotos"]) for i in com_foto) / len(com_foto), 1) if com_foto else 0,
        "amostra_foto": amostra,
        "foto_abre_sem_referer": await _foto_abre(amostra) if amostra else None,
        "tempo_s": round(time.time() - inicio, 1),
        "erro": erro,
    }


def _veredito(r: dict) -> str:
    if r["erro"]:
        return "ERRO no scraper"
    if not r["anuncios"]:
        return "0 anúncios — bloqueado ou parser quebrado (rode diagnosticar-scraper)"
    if not r["com_foto"]:
        return "sem foto — achar onde o portal põe a imagem e ajustar o scraper"
    if r["foto_abre_sem_referer"] != "ok":
        return "foto não abre direto — precisa do proxy de imagem (F1.9)"
    if r["com_foto"] < 0.8 * r["anuncios"]:
        return "foto em parte dos anúncios — conferir"
    return "OK"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--portais", nargs="*", default=list(PORTAIS), choices=list(PORTAIS))
    ap.add_argument("--json", help="grava o resultado neste arquivo")
    args = ap.parse_args()

    # Um portal por vez, de propósito: em paralelo seria outra carga sobre os
    # portais que não a de uma busca normal.
    resultados = [await diagnosticar(p) for p in args.portais]

    print(f"\nBusca de referência: {CIDADE} — R$ {PRECO_MIN:,} a {PRECO_MAX:,} — {QUARTOS} quartos\n")
    print(f"{'portal':<13}{'anúncios':>9}{'c/ foto':>9}{'média':>7}  {'foto abre?':<16} veredito")
    for r in resultados:
        print(f"{r['portal']:<13}{r['anuncios']:>9}{r['com_foto']:>9}{r['media_fotos']:>7}  "
              f"{str(r['foto_abre_sem_referer'] or '-'):<16} {_veredito(r)}")
        if r["erro"]:
            print(f"{'':<13}{r['erro']}")

    if args.json:
        Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nGravado em {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
