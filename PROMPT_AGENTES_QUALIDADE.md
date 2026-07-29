# Prompt — 3 Agentes de Qualidade (PriceRadar): imputar, enriquecer, blindar

> **Como usar:** cole este arquivo inteiro como mensagem inicial em uma nova sessão do Claude Code
> com acesso ao projeto. É autossuficiente — traz contexto, diagnóstico real e a especificação dos
> 3 agentes, cada um amarrado a um Insight medido.

---

## Contexto

**PriceRadar** — app interno da MRV para inteligência de precificação imobiliária. Backend Python +
FastAPI em `priceradar/backend/` (porta 8002), frontend React em `priceradar/frontend/` (5173).
A busca (`services/search.py`) dispara scrapers em paralelo, deduplica por URL, faz dedup
cross-portal via RF, calcula variação MRV e passa por um refinador Random Forest
(`services/rf_refiner.py`) antes de devolver.

**A coleta de volume já foi resolvida** (paginação + fallback Playwright nos scrapers): a busca de
referência hoje devolve **46 empreendimentos** (era ~2). O próximo salto é de **qualidade** — e os
dados abaixo, medidos numa execução real, mostram exatamente onde está o problema.

## Diagnóstico medido (busca de referência: Fortaleza-CE, R$280k–500k, 2 quartos)

- **Volume:** 118 anúncios brutos → **46 finais** (≈61% descartados por dedup + RF refiner).
- **Distribuição `preco_m2`:** min 2.500 · p25 5.074 · **mediana 6.713** · p75 8.317 · max 10.256 ·
  desvio-padrão 1.964.
- **Outliers:** 2 anúncios a **R$2.500–2.672/m²** (≈37% da mediana) — quase certamente valor de
  **entrada/parcela**, não preço total. Contaminam a média e o p25.
- **Campos faltantes nos 46 finais:** `construtora` ausente em **39/46 (85%)** · `nome_empreendimento`
  genérico (= nome do anúncio) em **28/46 (61%)** · `vagas` em 5 · `banheiros` em 1.
- **`rf_score`:** médio 0.677, com vários em 0.0 — sinal de que o refinador pune duro features
  faltantes.

**Conclusão:** o refinador está (a) descartando anúncios válidos só porque têm features faltantes, e
(b) deixando passar outliers de preço de entrada. E a extração de construtora/nome por regex falha na
maioria. São esses 3 pontos que os agentes devem atacar.

## Estado atual do código (ler antes de mexer)

- `services/rf_refiner.py` — `refinar_com_random_forest()` usa `IsolationForest`
  (`contamination=0.15`) + `RandomForestRegressor`; reprova quem está além de `2.0` desvios do
  resíduo. Com poucas amostras, devolve tudo com `rf_score=1.0`. **Hoje descarta em vez de imputar.**
- `scraper/parser.py` — `extrair_construtora()` e `extrair_nome_empreendimento()` são heurísticas por
  regex (lista pequena de construtoras + padrões "Construtora X"). É a causa dos 85%/61% de falha.
- `services/search.py` — orquestra: dedup URL → `deduplicar_cross_portal()` → variação MRV →
  `refinar_com_random_forest()`. É onde o pipeline é montado.

---

## Skills a usar (procure e aplique ANTES de codar)

Esta sessão tem skills do Claude Code. **Antes de agir, invoque a skill `treinar-avaliar-rf`** para
estabelecer o baseline das métricas de RF, e use `validar-busca` como gate a cada mudança. Não
improvise esses procedimentos — as skills padronizam a medição e evitam regressão.

- **`treinar-avaliar-rf`** → usada pelos **Agentes 1 e 2**. Treina/avalia os modelos RF com métricas
  reais (MAE da predição de preço/m², taxa de descarte, recall de empreendimentos válidos). É como
  cada agente prova que melhorou sem cortar válidos — rode antes (baseline) e depois (resultado).
- **`validar-busca`** → usada por **todos**. Sobe o backend na 8002, faz a busca de referência e
  reporta total bruto → dedup → após RF, por portal. Gate obrigatório: compare o total final com o
  baseline de 46 a cada alteração; ele não pode cair.

> As skills `diagnosticar-scraper` e `adicionar-fonte` são de **coleta** — não se aplicam a estes 3
> agentes de qualidade. Não as use aqui.

---

## Agente 1 — Imputação (Insight 2: parar de descartar por feature faltante)

**Objetivo:** elevar o total final reduzindo descartes indevidos — sem deixar entrar lixo.

Responsabilidades:
1. No `rf_refiner.py`, **separar "outlier de preço" de "dado incompleto"**. Hoje os dois levam a
   descarte; só o primeiro deveria.
2. **Imputar features faltantes** (`vagas`, `banheiros`, e quando fizer sentido `quartos`) com
   `RandomForestRegressor`/`Classifier` treinado nos próprios resultados, em vez de reprovar o
   anúncio. Marcar o campo como imputado e **penalizar levemente** o `rf_score` (não zerar).
3. Tornar o filtro **conservador**: só reprovar com altíssima confiança; nunca filtrar abaixo de um
   mínimo de amostras (já existe esse guard — revisar o limiar).

**Critério de sucesso (medir com `treinar-avaliar-rf` + `validar-busca`):** total final sobe acima de
46 na busca de referência; taxa de descarte cai de ~61%; nenhum outlier de preço real volta a passar.

## Agente 2 — Blindagem contra outliers de entrada (Insight 1: split por preço relativo)

**Objetivo:** remover com confiança os anúncios cujo `preco_m2` é preço de entrada/parcela, não valor
total — sem usar só desvio-padrão global (que é frágil com poucos dados).

Responsabilidades:
1. Adicionar uma "árvore" de decisão explícita por **preço relativo ao grupo** (mesma cidade +
   nº de quartos): reprovar `preco_m2` abaixo de ~50% da mediana do grupo (ajustável) — pega os
   R$2.500/m² que hoje passam.
2. Integrar essa regra ao score do `rf_refiner.py` de forma que **funcione mesmo com poucas amostras**
   (quando o `RandomForestRegressor` ainda não é confiável).
3. Não reprovar imóveis legitimamente baratos (ex.: kitnet pequena) — calibrar pelo grupo, não por
   um piso absoluto.

**Critério de sucesso:** os 2 outliers de R$2.500–2.672/m² da busca de referência são reprovados; a
mediana e o p25 de `preco_m2` sobem; nenhum imóvel válido de preço baixo é removido em excesso.

## Agente 3 — Enriquecimento de construtora e nome (Insight 3)

**Objetivo:** preencher `construtora` (hoje 85% vazio) e `nome_empreendimento` (61% genérico).

Responsabilidades:
1. Substituir/complementar as regex de `parser.py` por uma extração mais robusta: lista ampliada de
   construtoras conhecidas (nacional + regionais do Nordeste/CE), normalização, e — onde der —
   um **classificador RF** sobre features textuais da descrição (presença de tokens
   "Construtora/Incorporadora", padrões de nome de empreendimento, capitalização) para decidir se um
   trecho é nome de empreendimento/construtora.
2. Melhorar `extrair_nome_empreendimento()` para não cair no nome genérico do anúncio.
3. Não inventar dados: quando não houver evidência, manter `None` (melhor vazio que errado).

**Critério de sucesso:** `construtora` preenchida em uma fração bem maior que 15%; `nome_empreendimento`
genérico cai bem abaixo de 61% — medido contando os campos nos resultados da busca de referência.

---

## Restrições

- Código/comentários/logs em **português**, no padrão dos arquivos existentes.
- **Não regredir:** `MOCK=true` deve continuar funcionando; a busca devolve resposta mesmo se um
  scraper falhar (`return_exceptions=True`). Os 3 agentes mexem em **qualidade/refino**, não na coleta.
- Chave da ScraperAPI fica em `.env` (`SCRAPERAPI_KEY`) — nunca hardcode nem comite. (Cota esgotada
  até ~09/07; VivaReal/Zap hoje vêm via fallback Playwright — não quebrar esse caminho.)
- Performance: o refino roda em memória sobre os resultados já coletados; deve ser rápido (sub-segundo
  para ~120 itens). Não adicionar I/O de rede no caminho do refino.

## Validação final (obrigatório — runtime)

1. Rode `validar-busca` ANTES de qualquer mudança e registre o baseline (total 46, distribuição,
   faltantes).
2. Após cada agente, rode `treinar-avaliar-rf` (Agentes 1/2) e `validar-busca` (todos) e compare.
3. Reporte uma tabela **antes × depois**: total final, % descartado, nº de outliers que passaram,
   % com construtora, % com nome de empreendimento real.
4. Confirme que o total final **não caiu** e que `MOCK=true` ainda funciona.
