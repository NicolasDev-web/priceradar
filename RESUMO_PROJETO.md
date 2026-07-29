# PriceRadar — Resumo do Projeto

> Aplicação web interna da MRV para **inteligência competitiva de precificação imobiliária**.
> Coleta anúncios de apartamentos à venda em portais concorrentes, calcula o preço/m² praticado
> e compara com o referencial de preço da MRV.

**Atualizado em:** 29/07/2026
**Status:** Funcional localmente. Coleta estável e sem custo de proxy.

---

## 1. O que o PriceRadar entrega

Um número: **o preço/m² mediano praticado pelos concorrentes** num recorte (cidade, faixa de preço,
tipologia), comparado ao referencial MRV. Tudo o mais — gráficos, histórico, Excel — existe para
sustentar e contextualizar esse número.

A mediana é o número de referência, não a média: um único anúncio com área agregada desloca a média
e não move a mediana.

---

## 2. Arquitetura

```
PrecificacaoBruninho/
└── priceradar/
    ├── backend/                    # API Python (FastAPI), porta 8002
    │   ├── main.py                 # Endpoints
    │   ├── models.py               # Schemas Pydantic
    │   ├── scraper/
    │   │   ├── http.py             # Camada de acesso com escalonamento
    │   │   ├── browser.py          # Playwright (último nível de fallback)
    │   │   ├── parser.py           # Extração de construtora, nome, preço, área
    │   │   ├── chavesnamao.py      # JSON-LD, acesso direto
    │   │   ├── vivareal.py         # JSON-LD
    │   │   ├── zapimoveis.py       # JSON-LD
    │   │   ├── imovelweb.py        # Cards HTML
    │   │   └── olximoveis.py       # Desligado — parser defasado
    │   ├── services/
    │   │   ├── search.py           # Orquestração do pipeline
    │   │   ├── validacao.py        # Contrato de sanidade na fronteira
    │   │   ├── deduplicador.py     # Dedup cross-portal por chave de bloqueio
    │   │   ├── rf_refiner.py       # Imputação + blindagem de outliers
    │   │   ├── historico_fontes.py # Taxa de sucesso por fonte
    │   │   └── export.py           # Excel (openpyxl)
    │   ├── repositories/           # Histórico, cache, referencial MRV
    │   ├── database/               # SQLite async + migração leve
    │   └── tests/                  # 46 testes (pytest)
    └── frontend/                   # SPA React (Vite + TypeScript), porta 5173
```

### Pipeline de uma busca

```
coleta paralela (4 portais)
  → validação de fronteira      ← descarta locação, faixa de área, tipologia errada
  → filtro de bairro
  → dedup por URL
  → dedup cross-portal          ← chave de bloqueio; localização é obrigatória
  → variação vs. referencial MRV
  → refino (imputação + banda de outlier por tipologia)
  → resposta + diagnóstico da coleta
```

### Stack

| Camada | Tecnologias |
|---|---|
| Backend | Python, FastAPI, uvicorn, SQLAlchemy async + aiosqlite, Pydantic v2 |
| Coleta | curl-cffi, httpx, BeautifulSoup4 + lxml, Playwright (fallback) |
| Refino | scikit-learn, numpy |
| Frontend | React 18, Vite, TypeScript, Tailwind, Recharts, axios |
| Banco | SQLite |

---

## 3. Como a coleta funciona

### Escalonamento de acesso (`scraper/http.py`)

```
1. curl-cffi (TLS de Chrome real)  → grátis, ~1s      ← resolve a maioria
2. ScraperAPI (proxy rotativo)     → 1 crédito, ~5-25s
3. Playwright (browser real)       → grátis, ~15-25s  ← a cargo de cada scraper
```

O ponto-chave: VivaReal, Zap e ImovelWeb **não bloqueiam por User-Agent — bloqueiam pela assinatura
TLS/JA3**. `httpx` tem assinatura de biblioteca Python, reconhecível de imediato. `curl-cffi` replica
a de um Chrome real, e os mesmos portais que devolviam 403 passam a devolver 200.

Consequência prática: uma busca completa hoje consome **zero crédito** de proxy.

### Fontes

| Portal | Estratégia | Volume típico | Custo |
|---|---|---|---|
| zapimoveis | curl-cffi + JSON-LD, 2 págs | ~55 | 0 |
| chavesnamao | curl-cffi + JSON-LD, 12 págs | ~40 | 0 |
| vivareal | curl-cffi + JSON-LD, 2 págs | ~25 | 0 |
| imovelweb | curl-cffi + cards HTML, 2 págs | ~6 | 0 |
| olx | desligado — parser defasado (RSC) | — | — |
| mercadolivre | desligado — só renderiza com JS | — | — |
| quintoandar | desligado — listagem client-side | — | — |
| netimoveis | desligado — inventário só em MG | — | — |

---

## 4. Resultados da busca de referência

Fortaleza-CE, R$280k–500k, 2 quartos:

| Métrica | 21/06 | 29/07 |
|---|---:|---:|
| Empreendimentos | 46 | **85** |
| Tempo | ~120s | **7-45s** |
| Créditos por busca | ~6 | **0** |
| max / mediana (outlier) | 2,52 | **1,35** |
| Anúncios de locação | 2 | **0** |
| Anúncios com faixa de área | 8 | **0** |

---

## 5. Limitações conhecidas

1. **Amostra, não censo.** ~85 anúncios de 4 portais não são o mercado inteiro. É indicador de
   posicionamento, não medida exata.
2. **Anúncio ≠ venda.** Preço anunciado tem gordura de negociação.
3. **`construtora` fica vazia na maioria dos casos (~6%).** A lista de construtoras conhecidas foi
   podada de termos ambíguos ("Sky", "You", "Morada Nova" — que é cidade do CE) porque geravam nome
   errado. Preencher de verdade exige outra fonte de dados, não regex.
4. **O campo `bairro` traz endereço de rua** em VivaReal, Zap e ImovelWeb — só o ChavesNaMão traz
   bairro de fato. Isso limita o filtro de bairro e a dedup por localização.
5. **KPI sobre tipologias misturadas não é acionável.** 1 quarto custa ~14.000/m² e 3 quartos
   ~6.000/m² na mesma cidade. Buscar sem filtro de tipologia produz um número sem significado —
   sempre filtre por quartos.
6. **Fragilidade estrutural.** Os portais podem mudar de layout a qualquer momento. Os testes
   detectam a quebra rápido, mas não a impedem.
7. **Cobertura fora de Fortaleza não validada.** Cada praça nova precisa ser conferida.
8. **Local-only.** Sem deploy, sem autenticação, sem multiusuário.

---

## 6. Como rodar

```bash
# Backend
cd priceradar/backend
python -m venv venv && venv/Scripts/activate     # Windows
pip install -r requirements.txt
playwright install chromium                       # só para o fallback
cp .env.example .env                              # preencha se for usar ScraperAPI
uvicorn main:app --port 8002

# Frontend
cd priceradar/frontend
npm install && npm run dev

# Testes
cd priceradar/backend && python -m pytest tests/ -q
```

---

## 7. Próximos passos

1. **Definir o deploy** — servidor interno vs. cloud. É o que falta para "entregar ao comercial".
2. **Autenticação**, se for multiusuário.
3. **Corrigir o campo `bairro`** — separar logradouro de bairro nos parsers; destrava o filtro de
   bairro e melhora a dedup.
4. **KPI por tipologia** — quebrar o preço/m² por nº de quartos na interface.
5. **Reescrever o parser do OLX** (payload RSC) — o acesso já está destravado.
6. **Validar novas praças** antes de prometê-las ao time.
