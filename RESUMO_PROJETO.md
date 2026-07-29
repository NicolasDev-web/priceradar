# PriceRadar — Resumo do Projeto

> Aplicação web interna da MRV para **inteligência competitiva de precificação imobiliária**.
> Coleta anúncios de apartamentos à venda em portais concorrentes (VivaReal e Zap Imóveis),
> calcula estatísticas de preço/m² e compara com o referencial de preço da MRV.

**Data do resumo:** 09/06/2026
**Status:** Funcional (rodando localmente), com pontos de instabilidade conhecidos.

---

## 1. Visão geral

O PriceRadar permite ao time da MRV pesquisar empreendimentos concorrentes por **cidade, faixa de
preço, número de quartos e bairro (opcional)**. A aplicação:

- Faz scraping em tempo real dos portais VivaReal e Zap Imóveis;
- Consolida os resultados, remove duplicatas e calcula preço/m² médio, mínimo e máximo;
- Compara cada anúncio com um **referencial de preço da MRV** (cadastrável), mostrando a variação percentual;
- Apresenta gráficos (distribuição de preços e evolução histórica);
- Exporta os resultados para **Excel formatado**;
- Mantém **histórico** de buscas e usa **cache** para repetir buscas instantaneamente.

---

## 2. Arquitetura

```
PrecificacaoBruninho/
└── priceradar/
    ├── backend/          # API Python (FastAPI)
    │   ├── main.py                 # Endpoints da API
    │   ├── models.py               # Schemas Pydantic
    │   ├── scraper/
    │   │   ├── http.py             # Helper ScraperAPI (retry + timeout)
    │   │   ├── vivareal.py         # Scraper VivaReal (JSON-LD)
    │   │   ├── zapimoveis.py       # Scraper Zap (JSON-LD)
    │   │   ├── olximoveis.py       # Scraper OLX (desativado — bloqueia)
    │   │   └── parser.py           # Extração de construtora, nome, etc.
    │   ├── services/
    │   │   ├── search.py           # Orquestração paralela dos scrapers
    │   │   └── export.py           # Geração do Excel (openpyxl)
    │   ├── repositories/
    │   │   ├── busca_repo.py       # Histórico + cache de buscas
    │   │   └── empreendimento_repo.py  # Referencial MRV + série histórica
    │   ├── database/
    │   │   ├── connection.py       # SQLite async + migração leve
    │   │   └── models_db.py        # Tabelas ORM (SQLAlchemy)
    │   └── priceradar.db           # Banco SQLite
    └── frontend/         # SPA React (Vite + TypeScript)
        └── src/
            ├── App.tsx
            ├── api/client.ts       # Cliente HTTP (axios)
            ├── types/index.ts
            └── components/         # SearchForm, ResultCard, KpiBar, gráficos, etc.
```

### Stack tecnológica

| Camada | Tecnologias |
|---|---|
| **Backend** | Python, FastAPI, uvicorn, SQLAlchemy (async) + aiosqlite, Pydantic v2, httpx, BeautifulSoup4 + lxml, openpyxl |
| **Frontend** | React 18, Vite, TypeScript, Tailwind CSS, Recharts, axios, lucide-react |
| **Scraping** | ScraperAPI (proxy que contorna o bloqueio anti-bot dos portais) |
| **Banco** | SQLite |

---

## 3. Como funciona o scraping (decisão-chave)

Os portais (VivaReal, Zap) são SPAs Next.js protegidas por anti-bot (Cloudflare). A solução:

1. **ScraperAPI** como proxy — rotaciona IPs e usa IP brasileiro (`country_code=br`).
2. **Extração via JSON-LD** — em vez de raspar HTML com seletores CSS frágeis, lemos o bloco
   `<script type="application/ld+json">` com `@type: ItemList`, que contém preço, área, quartos,
   banheiros, endereço e URL de cada imóvel de forma estruturada e estável.
3. **`render=false`** — como os dados já vêm no HTML inicial, **não** precisamos renderizar
   JavaScript. Isso reduziu o tempo de resposta de **~55s para ~2-5s** por portal.

### Formato de URL por portal
- **VivaReal:** `/venda/{estado-por-extenso}/{cidade}/apartamento_residencial/` (ex: `ceara`, não `ce`)
- **Zap:** `/venda/apartamentos/{estado}+{cidade}/`

---

## 4. Funcionalidades implementadas

- ✅ Busca multi-portal (VivaReal + Zap) em paralelo (`asyncio.gather`)
- ✅ Filtro por cidade, faixa de preço e número de quartos
- ✅ Filtro por bairro (aplicado **após** o scraping — ver problemas)
- ✅ Extração do nome do empreendimento e da construtora a partir da descrição
- ✅ Cálculo de preço/m² médio, mínimo e máximo
- ✅ Referencial de preço MRV cadastrável + cálculo de variação percentual por anúncio
- ✅ Deduplicação de anúncios por URL
- ✅ Gráfico de distribuição de preços (com linha de referência MRV)
- ✅ Gráfico de evolução histórica de preço/m²
- ✅ Exportação para Excel formatado (cores condicionais, médias, congelamento de cabeçalho)
- ✅ Histórico de buscas (persistido em SQLite)
- ✅ **Cache de buscas** — repetir uma busca idêntica recente devolve resultado em ~0,02s
- ✅ Identidade visual MRV (verde #0B5A42, laranja #F39200)

### Ganhos de performance obtidos
| Otimização | Antes | Depois |
|---|---|---|
| `render=true` → `render=false` | ~46s | ~5-8s |
| Exportação Excel (não refaz scraping) | ~50s | ~0,06s |
| Cache de buscas repetidas | ~8s | ~0,02s |

---

## 5. Problemas principais e limitações

### 🔴 Críticos / Riscos

1. **Dependência total da ScraperAPI (instável e limitada)**
   - O plano gratuito tem **1.000 requisições/mês** e apresenta **erros 500 intermitentes**.
   - Cada busca consome 2 requisições (VivaReal + Zap), então o limite é de ~500 buscas/mês.
   - Quando a ScraperAPI falha, a busca volta vazia ou parcial. Há retry (2 tentativas) e timeout
     de 25s, mas não há fallback real.

2. **Chave da ScraperAPI precisa estar protegida**
   - A chave fica em `backend/.env` (correto), mas **deve nunca ser commitada**. Confirmar que
     `.env` está no `.gitignore`.

3. **Fragilidade do scraping**
   - Se os portais mudarem o formato da URL ou removerem o JSON-LD, o scraping quebra.
   - O VivaReal exige nome do estado por extenso — qualquer cidade nova precisa estar no mapa de estados.

### 🟠 Funcionais

4. **Filtro de bairro é pós-scraping (impreciso)**
   - Os portais retornam 404 ao filtrar bairro pela URL, então buscamos a cidade inteira e
     filtramos pelo texto do endereço. Como só vêm ~30 resultados por portal, **bairros com poucos
     anúncios podem retornar vazio** mesmo existindo imóveis.

5. **OLX desativado**
   - O OLX bloqueia requisições de servidor (403). Está desligado por padrão (`HABILITAR_OLX=false`).
     Logo, a cobertura é de apenas 2 dos 3 portais planejados.

6. **Resultados limitados a ~30 por portal**
   - O JSON-LD traz apenas a primeira página de resultados. Não há paginação implementada.

7. **Qualidade da extração de construtora/empreendimento é heurística**
   - Baseada em regex sobre a descrição. Acerta em muitos casos, mas erra em outros
     (ex: capturar "Fortaleza" ou "Torre B" como construtora). Vários anúncios ficam sem construtora.

8. **Duplicatas entre portais**
   - O mesmo imóvel pode aparecer no VivaReal e no Zap com URLs diferentes — a deduplicação por URL
     não os elimina (aparecem dois cards iguais).

### 🟡 Técnicos / Manutenção

9. **`requirements.txt` desatualizado**
   - Ainda lista `playwright` (não é mais usado — foi abandonado por incompatibilidade com Windows).
   - **Faltam** `sqlalchemy` e `aiosqlite`, que são usados pelo banco. Instalação limpa pode falhar.

10. **Sem testes automatizados**
    - Não há suíte de testes. Toda validação foi manual/iterativa.

11. **Apenas ambiente local**
    - Backend em `localhost:8001`, frontend em `localhost:5173`. Não há deploy nem autenticação.
    - O `MOCK=true` permite rodar sem ScraperAPI (dados fictícios) para desenvolvimento.

12. **Cidade fixa em testes**
    - O foco atual é Fortaleza-CE. Outras cidades funcionam, mas foram pouco testadas.

---

## 6. Configuração (variáveis de ambiente)

`backend/.env`:
```
MOCK=false                 # true = dados fictícios, sem ScraperAPI
SCRAPERAPI_KEY=<chave>     # obrigatória para scraping real
CACHE_MINUTOS=60           # validade do cache de buscas
SCRAPER_TIMEOUT=25         # timeout por requisição (segundos)
HABILITAR_OLX=false        # OLX desativado (bloqueia)
```

`frontend/.env.local`:
```
VITE_API_URL=http://localhost:8001
```

---

## 7. Próximos passos sugeridos (priorizados)

1. **Corrigir `requirements.txt`** — remover `playwright`, adicionar `sqlalchemy` e `aiosqlite`. *(rápido, importante)*
2. **Avaliar plano pago da ScraperAPI** ou alternativa — resolve instabilidade e limite de requisições.
3. **Melhorar deduplicação cross-portal** — comparar por nome+área+preço, não só URL.
4. **Reforçar extração de construtora** — lista de construtoras conhecidas + validação.
5. **Paginação** — buscar mais de 30 resultados por portal.
6. **Testes automatizados** — ao menos para os parsers de JSON-LD.
7. **Deploy + autenticação** — se for uso por mais pessoas do time.
```
