# Skill: diagnosticar-scraper

Roda um scraper isolado contra a busca de referência e reporta seu status.

## Como usar

```
/diagnosticar-scraper <nome_do_scraper>
```

Exemplos: `/diagnosticar-scraper quintoandar`, `/diagnosticar-scraper chavesnamao`

## O que fazer

1. Leia o arquivo `.env` em `priceradar/backend/.env` para carregar as variáveis de ambiente.
2. Entre no diretório do backend: `priceradar/backend/`
3. Execute o script abaixo com o venv ativado:

```python
# Executa via: priceradar/backend/venv/Scripts/python.exe -c "..."
import asyncio, os, time, sys
from pathlib import Path

# Carrega .env
for linha in Path('.env').read_text().splitlines():
    if '=' in linha and not linha.startswith('#'):
        k, v = linha.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, '.')
portal = "<NOME>"  # substituir pelo argumento

inicio = time.time()
try:
    mod = __import__(f"scraper.{portal.replace('-', '_')}", fromlist=[""])
    fn = getattr(mod, f"scrape_{portal.replace('-', '_')}", None) or getattr(mod, f"scrape_{portal}", None)
    resultados = asyncio.run(fn("Fortaleza, CE", 280000, 500000, 2))
    tempo = round(time.time() - inicio, 2)
    print(f"Portal     : {portal}")
    print(f"Status     : OK")
    print(f"Resultados : {len(resultados)}")
    print(f"Tempo      : {tempo}s")
    if resultados:
        print(f"Amostra    : {resultados[0].get('nome_anuncio')} | R${resultados[0].get('preco'):,.0f} | {resultados[0].get('area_m2')}m²")
except Exception as e:
    print(f"Portal     : {portal}")
    print(f"Status     : ERRO — {e}")
    print(f"Tempo      : {round(time.time() - inicio, 2)}s")
```

4. Reporte uma tabela com:
   - Portal, Status HTTP (se aplicável), Bytes recebidos, Nº de resultados, Tempo
   - Diagnóstico: `ok` / `bloqueado (status 403/429)` / `parsing quebrado (0 resultados + HTML grande)` / `sem resultado (HTML pequeno/vazio)` / `dependente de ScraperAPI (cota esgotada?)`

5. **NUNCA** exponha o valor de `SCRAPERAPI_KEY` na saída.
