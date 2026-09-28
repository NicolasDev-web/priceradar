"""Inspeção local do payload React Server Components da busca pública da OLX."""
import asyncio
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scraper.http import buscar_html
from scraper.olximoveis import build_olx_url


async def main() -> None:
    url = build_olx_url("fortaleza", "ce", 280_000, 500_000)
    html = await buscar_html(url, "OLX-DIAG") or ""
    scripts = re.findall(r"self\.__next_f\.push\((\[.*?\])\)</script>", html, re.DOTALL)
    chunks: list[str] = []
    for script in scripts:
        try:
            valor = json.loads(script)
        except json.JSONDecodeError:
            continue
        if len(valor) > 1 and isinstance(valor[1], str):
            chunks.append(valor[1])

    texto = "".join(chunks)
    print({
        "bytes_html": len(html),
        "scripts_rsc": len(scripts),
        "caracteres_rsc": len(texto),
        "listId": texto.count("listId"),
        "subject": texto.count("subject"),
        "location": texto.count("location"),
        "properties": texto.count("properties"),
    })

    arrays: list[list[dict]] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"ads":', texto):
        try:
            valor, _ = decoder.raw_decode(texto, match.end())
        except json.JSONDecodeError:
            continue
        if isinstance(valor, list) and valor and isinstance(valor[0], dict):
            arrays.append(valor)
    print("arrays_ads", [len(a) for a in arrays])
    if arrays:
        primeiro = arrays[0][0]
        print("chaves_primeiro", sorted(primeiro))
        print("primeiro_resumo", {
            chave: primeiro.get(chave)
            for chave in ("subject", "priceValue", "listId", "url", "location", "properties")
        })
    for termo in ("listId", "subject", "location", "pagination", "pageIndex", "nextPage"):
        indice = texto.find(termo)
        trecho = texto[max(0, indice - 180):indice + 500] if indice >= 0 else "não encontrado"
        print(f"\n[{termo}]\n{trecho}")


if __name__ == "__main__":
    asyncio.run(main())
