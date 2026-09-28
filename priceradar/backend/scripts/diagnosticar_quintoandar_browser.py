"""Teste local do QuintoAndar em navegador headless, sem contornar desafios."""
import asyncio
import pathlib
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scraper.browser import buscar_html_playwright


async def medir(cidade_slug: str) -> None:
    url = f"https://www.quintoandar.com.br/comprar/imovel/{cidade_slug}"
    html = await buscar_html_playwright(url, "QuintoAndar", 'a[href*="/imovel/"]') or ""
    soup = BeautifulSoup(html, "lxml")
    links = soup.select('a[href*="/imovel/"]')
    cards = [
        link for link in links
        if (link.get("href") or "").startswith("/imovel/")
        or "quintoandar.com.br/imovel/" in (link.get("href") or "")
    ]
    print({
        "cidade": cidade_slug,
        "bytes": len(html),
        "titulo": soup.title.get_text(strip=True) if soup.title else None,
        "links_imovel": len(links),
        "cards_compra": len(cards),
        "primeiros": [(c.get("href"), c.get("aria-label")) for c in cards[:3]],
    })


async def main() -> None:
    await medir("fortaleza-ce-brasil")
    await medir("sao-paulo-sp-brasil")


if __name__ == "__main__":
    asyncio.run(main())
