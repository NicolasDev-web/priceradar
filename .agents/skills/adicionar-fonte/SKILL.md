# Skill: adicionar-fonte

Template padronizado para criar um novo scraper consistente com os existentes.

## Como usar

```
/adicionar-fonte <nome_portal> <url_base_busca>
```

Exemplo: `/adicionar-fonte wimoveis https://www.wimoveis.com.br`

## Passos obrigatórios

### 1. Diagnosticar a URL de busca
Antes de criar o scraper, identifique:
- A URL de busca com filtros (cidade, preço, quartos)
- Como os dados estão no HTML: JSON-LD? `__NEXT_DATA__`? Cards HTML?
- Se precisa de JavaScript (Playwright) ou httpx direto basta

### 2. Criar o arquivo `priceradar/backend/scraper/<nome>.py`

Use esta estrutura obrigatória:

```python
"""<Nome> — scraping direto via httpx.

Estratégia: <descreva aqui>.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime
import httpx
from scraper.parser import calcular_preco_m2, extrair_construtora, normalizar_cidade

logger = logging.getLogger(__name__)

BASE_URL = "<url_base>"
MAX_PAGINAS = int(os.getenv("<NOME>_MAX_PAGINAS", "5"))

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def _build_url(cidade, estado, preco_min, preco_max, quartos, pagina=1):
    # Construir URL com parâmetros de busca e paginação
    ...

async def scrape_<nome>(
    cidade: str,
    preco_min: float,
    preco_max: float,
    quartos: int | None,
    bairro: str | None = None,
) -> list[dict]:
    # Retorna lista de dicts com os campos do Empreendimento
    # NUNCA lança exceção — sempre retorna [] em caso de falha
    ...
```

**Campos obrigatórios em cada dict retornado:**
`id`, `nome_anuncio`, `nome_empreendimento`, `construtora`, `cidade`, `bairro`,
`portal`, `preco`, `area_m2`, `preco_m2`, `quartos`, `banheiros`, `vagas`,
`descricao`, `url_anuncio`, `data_coleta`

### 3. Adicionar feature flag no `.env`

```
HABILITAR_<NOME>=true
<NOME>_MAX_PAGINAS=5
```

### 4. Registrar em `services/search.py`

```python
# Imports no topo:
from scraper.<nome> import scrape_<nome>

# Flag:
<NOME>_HABILITADO = os.getenv("HABILITAR_<NOME>", "true").lower() == "true"

# Na lista tarefas_candidatas:
if <NOME>_HABILITADO:
    tarefas_candidatas.append(("<nome>", scrape_<nome>(...)))
```

### 5. Validar com `/diagnosticar-scraper`

```
/diagnosticar-scraper <nome>
```

Confirme: resultados > 0, tempo < 30s, sem exceções.

### 6. Validar integração com `/validar-busca`

Compare contagem antes/depois de adicionar o scraper.
