# Prompt — Criação de 3 Agentes para Ampliar a Coleta de Empreendimentos (PriceRadar)

> **Como usar:** cole este arquivo inteiro como mensagem inicial em uma nova sessão do Claude Code
> (ou outra IA com acesso ao código do projeto). Ele é autossuficiente — contém o contexto, o
> diagnóstico real do problema e as especificações dos 3 agentes.

---

## Contexto do projeto

**PriceRadar** é uma aplicação interna da MRV para inteligência competitiva de precificação
imobiliária. Coleta anúncios de apartamentos à venda em portais concorrentes, calcula preço/m² e
compara com um referencial de preço da MRV.

- **Backend:** Python + FastAPI (`priceradar/backend/`), SQLite (SQLAlchemy async), Pydantic v2,
  httpx, BeautifulSoup4. Roda em `localhost:8002`.
- **Frontend:** React + Vite + TypeScript (`priceradar/frontend/`), em `localhost:5173`.
- **Orquestração da busca:** `priceradar/backend/services/search.py` — dispara todos os scrapers em
  paralelo (`asyncio.gather`), deduplica por URL, calcula variação MRV e passa por um refinador
  Random Forest (`services/rf_refiner.py`) antes de devolver.
- **Scrapers existentes** (`priceradar/backend/scraper/`): `vivareal.py`, `zapimoveis.py`,
  `mercadolivre.py`, `imovelweb.py`, `netimoveisagent.py`, `chavesnamao.py`, `quintoandar.py`,
  `olximoveis.py`. Helpers: `http.py` (ScraperAPI), `browser.py`, `parser.py`.

## Problema a resolver

**A busca retorna pouquíssimos empreendimentos.** Precisamos achar **muito mais**. Em uma busca real
(Fortaleza-CE, R$280k–500k, 2 quartos) o volume por scraper foi medido assim:

| Scraper       | Resultados | Diagnóstico                                                        |
|---------------|-----------:|--------------------------------------------------------------------|
| vivareal      | 0          | Depende da **ScraperAPI com cota mensal esgotada** (creditsLeft=0) |
| zapimoveis    | 0          | Idem — ScraperAPI esgotada                                         |
| mercadolivre  | 0          | Roda ~20s e retorna 0 — provavelmente bloqueado/parsing quebrado   |
| imovelweb     | 2          | Volume muito baixo (sem paginação)                                 |
| netimoveis    | 0          | Roda ~15s e retorna 0 — quebrado                                   |
| chavesnamao   | 2          | Volume muito baixo (sem paginação)                                 |
| quintoandar   | 0          | **BUG**: `'bool' object has no attribute 'get'` ao parsear         |

**Causa-raiz:** o gargalo NÃO é a inteligência da busca — é a **coleta**: scrapers quebrados,
bloqueados, dependentes de uma API paga esgotada e sem paginação. O refinador Random Forest atual
(`rf_refiner.py`) ainda pode estar cortando resultados válidos por treinar com amostras pequenas.

## Tarefa

Criar **3 agentes especializados** que trabalhem em conjunto para **maximizar o número de
empreendimentos válidos** encontrados. Cada agente **usa Random Forest como ferramenta** dentro da
sua especialidade (Random Forest é um algoritmo de ML tabular — classificação/regressão — não um
mecanismo de "raciocínio" autônomo; use-o onde fizer sentido estatisticamente).

> ⚠️ **Antes de codar qualquer agente, rode um diagnóstico:** abra cada scraper, execute-o
> isoladamente e confirme o que está quebrado vs. bloqueado vs. sem paginação. Não confie só na
> tabela acima — ela é um retrato de um momento. Comece consertando o que dá retorno rápido.

---

### Agente 1 — Coletor / Reparador de Fontes (maior prioridade)

**Objetivo:** maximizar o volume bruto de anúncios coletados.

Responsabilidades:
1. **Consertar os scrapers quebrados**, começando pelo bug do `quintoandar.py`
   (`'bool' object has no attribute 'get'`), depois `netimoveis` e `mercadolivre` (0 resultados).
2. **Adicionar paginação** aos scrapers que só pegam a 1ª página (`imovelweb`, `chavesnamao` e os
   demais que suportarem) — buscar N páginas até esgotar ou atingir um teto configurável.
3. **Reduzir dependência da ScraperAPI** (cota esgotada): priorizar scrapers diretos (httpx +
   headers de browser) e usar a ScraperAPI só como fallback quando o acesso direto falhar.
4. **Avaliar novas fontes** (ex.: 123i, Loft, DFImóveis, Wimoveis, ZAP via mobile API) e implementar
   as viáveis.
5. **Uso de Random Forest:** treinar um classificador que, a partir de features da requisição
   (cidade, portal, faixa de preço, horário, taxa de sucesso histórica), **preveja quais fontes têm
   maior probabilidade de retornar resultados** e priorize-as / ajuste a ordem e o paralelismo.
   Persistir o histórico de sucesso por fonte para alimentar esse modelo.

**Critério de sucesso:** volume bruto coletado (antes de dedup) sobe de ~4 para **dezenas** de
anúncios na busca de referência (Fortaleza-CE, R$280k–500k, 2 quartos).

### Agente 2 — Deduplicador / Reconciliador (Random Forest no núcleo)

**Objetivo:** unificar o mesmo imóvel anunciado em portais diferentes **sem perder empreendimentos
distintos** (a dedup atual só compara URL, então o mesmo imóvel aparece duplicado entre portais).

Responsabilidades:
1. Detectar duplicatas reais entre portais comparando **nome, área, preço, nº de quartos, bairro e
   coordenadas/endereço** — não apenas URL.
2. **Uso de Random Forest:** treinar um classificador de pares (par de anúncios → "mesma unidade?
   sim/não") usando features de similaridade (diferença % de preço, diferença de área, similaridade
   textual de nome/endereço via fuzzy matching, mesmo bairro). Saída: clusters de anúncios que são o
   mesmo imóvel, mantendo um representante e registrando em quais portais aparece.
3. **Não** colapsar empreendimentos diferentes que por acaso tenham preço/área parecidos —
   priorizar recall de empreendimentos (errar para o lado de manter, não de descartar).

**Critério de sucesso:** duplicatas cross-portal somem, mas a contagem de empreendimentos **únicos**
não cai indevidamente.

### Agente 3 — Qualidade / Enriquecimento (substitui/evolui o `rf_refiner.py`)

**Objetivo:** garantir que o filtro de qualidade **não derrube anúncios válidos** (problema atual em
amostras pequenas) e enriquecer os dados faltantes.

Responsabilidades:
1. Revisar o `rf_refiner.py`: hoje ele usa `IsolationForest` + `RandomForestRegressor` e pode
   rejeitar válidos quando há poucas amostras. Tornar a filtragem **conservadora** (só remover
   outliers com altíssima confiança) e **nunca filtrar** abaixo de um mínimo de amostras.
2. **Uso de Random Forest:** usar `RandomForestRegressor` para **preencher campos faltantes**
   (ex.: estimar área quando ausente, inferir nº de quartos) em vez de descartar o anúncio, e para
   atribuir um `rf_score` de confiabilidade ao dado.
3. Melhorar a extração de **construtora** e **nome do empreendimento** (hoje heurística por regex,
   erra com frequência).

**Critério de sucesso:** taxa de anúncios descartados pelo refinador cai; campos faltantes são
preenchidos em vez de causar descarte.

---

## Skills recomendadas (criar e usar)

No Claude Code, **skills** são workflows reutilizáveis definidos em markdown dentro de
`.claude/skills/<nome>/SKILL.md`. Em vez de repetir o mesmo procedimento manualmente a cada
iteração, os agentes invocam a skill como um comando único. Crie as skills abaixo **antes** de
mexer nos agentes — elas padronizam as tarefas mais repetidas e protegem contra regressões. Cada
agente deve **usar** as skills relevantes em vez de improvisar o procedimento.

### Skill `diagnosticar-scraper` — usada pelo Agente 1

Roda um scraper isolado contra a busca de referência e reporta: status HTTP, tamanho da resposta,
contagem de resultados, tempo, e se há JSON-LD/bloqueio. É a primeira coisa a rodar ao mexer em
qualquer fonte — diferencia "quebrado" de "bloqueado" de "sem paginação".

```text
.claude/skills/diagnosticar-scraper/SKILL.md
---
Recebe o nome de um scraper. Importa a função scrape_<nome> de priceradar/backend/scraper/,
executa-a com (cidade="Fortaleza, CE", preco_min=280000, preco_max=500000, quartos=2), e reporta
em tabela: status, bytes recebidos, nº de resultados, tempo, e diagnóstico (ok / bloqueado /
parsing quebrado / sem resultado). Carrega o .env antes de importar. Nunca expõe a SCRAPERAPI_KEY.
```

### Skill `validar-busca` — usada por todos os agentes

Sobe (ou reusa) o backend na porta 8002 e dispara a busca de referência, reportando contagem por
portal, total bruto, total após dedup e total após refinamento. É o gate de validação obrigatório:
todo agente roda antes/depois da sua mudança e compara com o baseline (~2 após refinamento).

```text
.claude/skills/validar-busca/SKILL.md
---
Garante o backend rodando em localhost:8002 (sobe com uvicorn se necessário). Faz POST /api/buscar
com o payload de referência. Reporta: contagem por portal, total bruto, após dedup, após RF refiner,
tempo total. Confirma que MOCK=true ainda devolve dados e que nenhum scraper trava a busca.
```

### Skill `treinar-avaliar-rf` — usada pelos Agentes 2 e 3

Treina e avalia os modelos Random Forest (dedup de pares e qualidade/enriquecimento) com métricas
reais — não apenas "rodou". Evita o problema atual de o modelo cortar válidos sem ninguém medir.

```text
.claude/skills/treinar-avaliar-rf/SKILL.md
---
Treina o modelo RF alvo (classificador de duplicatas OU regressor de qualidade) sobre um conjunto
de anúncios coletados. Reporta métricas: para dedup → precision/recall/F1 de pares "mesma unidade";
para qualidade → MAE da predição de preço/m² e taxa de descarte. Faz validação cruzada. Sinaliza se
o modelo está descartando empreendimentos válidos (recall de empreendimentos < limiar).
```

### Skill `adicionar-fonte` — usada pelo Agente 1

Template padronizado para criar um novo scraper consistente com os existentes (assinatura da função,
feature flag `HABILITAR_<FONTE>`, registro no `search.py`, normalização de campos, fallback gracioso).

```text
.claude/skills/adicionar-fonte/SKILL.md
---
Dado o nome de um portal e sua URL de busca, gera um scraper novo em priceradar/backend/scraper/
seguindo o padrão dos existentes: função async scrape_<fonte>(cidade, preco_min, preco_max, quartos,
bairro), parsing para o schema Empreendimento, timeout + retry, feature flag HABILITAR_<FONTE>,
e registro na lista de tarefas do services/search.py. Roda diagnosticar-scraper ao final.
```

> **Observação:** se a sessão de destino não suportar skills nativas do Claude Code, trate cada bloco
> acima como um **script utilitário** equivalente (ex.: `scripts/diagnosticar_scraper.py`) — o valor
> está em padronizar e automatizar essas tarefas repetidas, não no mecanismo específico.

---

## Restrições e diretrizes

- **Idioma do código/comentários/logs:** português, seguindo o padrão dos arquivos existentes.
- **Segurança:** a chave da ScraperAPI fica em `priceradar/backend/.env` (`SCRAPERAPI_KEY`) —
  **nunca** hardcode nem comite. A cota está esgotada até ~09/07; trate ausência de crédito com
  fallback gracioso (não derrubar a busca).
- **Performance:** scrapers rodam em paralelo (`asyncio.gather` em `search.py`); mantenha timeout por
  fonte (hoje ~25s) e retry curto para erros transitórios. Volume não pode custar minutos de espera.
- **Não regredir:** a busca deve continuar funcionando com `MOCK=true` (dados fictícios) e devolver
  resposta mesmo se alguns scrapers falharem (`return_exceptions=True` já é usado).
- **Feature flags:** cada fonte é ligável por env (`HABILITAR_<FONTE>`); preserve esse padrão.

## Como validar (obrigatório — runtime, não só leitura de código)

1. Rode cada scraper isoladamente e capture a contagem **antes** e **depois** das correções.
2. Suba o backend (`uvicorn main:app --port 8002`) e faça a busca de referência via
   `POST /api/buscar` com `{"cidade":"Fortaleza, CE","preco_min":280000,"preco_max":500000,"quartos":2}`.
3. Reporte a contagem por portal, total bruto, total após dedup e total após refinamento —
   comparando antes/depois. O sucesso é **muito mais empreendimentos válidos** que o baseline atual
   (~2 após refinamento).
4. Confirme que nenhum scraper trava a busca e que o `MOCK=true` ainda funciona.
