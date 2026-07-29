"""
Script de descoberta: captura TODAS as chamadas de rede do Netimoveis
para identificar o endpoint AJAX que retorna os listings.
Executa headless=False para inspecionar visualmente se necessário.
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")


async def descobrir_endpoint():
    from playwright.async_api import async_playwright

    url = "https://www.netimoveis.com/venda/apartamento/sp/sao-paulo?preco_minimo=300000&preco_maximo=700000&dormitorios=2"

    print(f"Abrindo: {url}")
    print("Capturando TODAS as requisições de rede...\n")

    chamadas = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        async def capturar(response):
            url_resp = response.url
            status = response.status
            ct = response.headers.get("content-type", "")
            # Captura tudo que for JSON ou que pareça API
            if "json" in ct or "/api/" in url_resp or "imovel" in url_resp.lower() or "search" in url_resp.lower() or "listing" in url_resp.lower():
                tamanho = ""
                dados_preview = ""
                try:
                    body = await response.body()
                    tamanho = f"{len(body)} bytes"
                    if "json" in ct:
                        parsed = json.loads(body)
                        if isinstance(parsed, list):
                            dados_preview = f"[lista com {len(parsed)} items]"
                        elif isinstance(parsed, dict):
                            chaves = list(parsed.keys())[:8]
                            dados_preview = f"dict keys={chaves}"
                except Exception as e:
                    dados_preview = f"erro: {e}"
                chamadas.append({
                    "url": url_resp,
                    "status": status,
                    "content_type": ct,
                    "tamanho": tamanho,
                    "preview": dados_preview,
                })

        page.on("response", capturar)

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        print("Página carregada (domcontentloaded), aguardando networkidle...")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)

        await browser.close()

    print(f"\n{'='*70}")
    print(f"Total de chamadas JSON/API capturadas: {len(chamadas)}")
    print(f"{'='*70}\n")
    for c in chamadas:
        print(f"[{c['status']}] {c['url']}")
        print(f"       CT: {c['content_type']}")
        print(f"       Tamanho: {c['tamanho']}  |  Preview: {c['preview']}")
        print()

    # Tenta identificar o endpoint principal de listings
    print("\n--- CANDIDATOS A ENDPOINT DE LISTINGS ---")
    for c in chamadas:
        preview = c.get("preview", "")
        # Heurística: lista com muitos items ou dict com chave típica de listings
        if "lista com" in preview or any(k in preview for k in ["imovel", "listing", "result", "data"]):
            print(f"  ** {c['url']}")
            print(f"     {preview}")


asyncio.run(descobrir_endpoint())
