# Plano de melhorias — fotos, filtro de banheiros, mapa e busca

> Levantado em 23/09/2026 a partir do código da branch `main` (commit `33353c0`).
> Caminhos de código são relativos a `priceradar/` (ex.: `backend/models.py`).
> Cada frente tem um agente dedicado em `.claude/agents/`. Para disparar um deles
> no Claude Code: *"use o agente `<nome>` para a tarefa F1.2 do PLANO_MELHORIAS.md"*.

## Visão geral

| Frente | Agente | Tamanho | Mexe no contrato da API? |
| --- | --- | --- | --- |
| F0 — Contrato compartilhado | (feito antes, por quem for começar) | P | **Sim** — base das outras |
| F1 — Fotos dos empreendimentos | `fotos-empreendimentos` | G | Sim (`fotos`) |
| F2 — Filtro de banheiros | `filtro-banheiros` | P | Sim (`banheiros` no request) |
| F3 — Mapa (API de tiles) | `mapa-tiles` | P/M | Não |
| F4 — Busca: mais sites e mais volume | `coleta-fontes` | G | Não |

### Ordem recomendada

```text
F0 (contrato)  ──►  F2 (banheiros)      ─┐
               ──►  F1 (fotos)           ├──►  validar-busca  ──►  PR
F3 (mapa)      — independente, em paralelo
F4 (coleta)    — independente, contínuo; ao criar fonte nova já extrai fotos (F1)
```

- **F0 → F2, e F3 em paralelo, primeiro**: pequenas e entregam valor visível rápido.
- **F1 antes de F4 terminar**: toda fonte nova de F4 já deve nascer extraindo foto, senão
  vira retrabalho.
- Os agentes que mexem em `models.py`, `types/index.ts`, `database/connection.py` e
  `repositories/busca_repo.py` (F1 e F2) **não devem rodar em paralelo na mesma branch** —
  conflitam nos mesmos arquivos. Rode em sequência ou em worktrees separadas e faça merge.

---

## F0 — Contrato compartilhado (pré-requisito de F1 e F2) — ✅ feito

Os dois campos novos atravessam as mesmas 5 camadas. Fazer de uma vez evita dois
conflitos nos mesmos arquivos.

| # | Tarefa | Arquivo |
| --- | --- | --- |
| F0.1 | `Empreendimento.fotos: list[str] = []` e `BuscaRequest.banheiros: int \| None = None` | `backend/models.py` |
| F0.2 | Coluna `fotos` (TEXT com JSON) em `empreendimentos`; coluna `banheiros` e `tipo_edificacao` em `buscas`; migrações em `_migrar_colunas` | `backend/database/models_db.py`, `backend/database/connection.py` |
| F0.3 | Gravar/ler `fotos` e `banheiros` no `salvar_busca` e no `buscar_cache_recente` | `backend/repositories/busca_repo.py` |
| F0.4 | Espelhar no TS: `fotos?: string[]` em `Empreendimento`, `banheiros?: number \| null` em `BuscaRequest` | `frontend/src/types/index.ts` |

**Bug encontrado no caminho:** `buscar_cache_recente` compara cidade, preço, quartos e
bairro, mas **não** `tipo_edificacao`. Uma busca "só torre" feita logo depois de uma busca
sem filtro devolve o resultado sem filtro, do cache. O `banheiros` teria o mesmo problema.
F0.2/F0.3 corrigem os dois juntos.

---

## F1 — Fotos dos empreendimentos (agente `fotos-empreendimentos`)

**Situação hoje:** nenhum scraper extrai imagem (`grep -i "image\|foto"` em `scraper/` não
acha nada). O card não tem área de imagem.

**Estratégia:** usar só as fotos que já vêm na página de resultados de cada portal — custo
zero de requisição. Não buscar a página de detalhe de cada anúncio: multiplicaria as
requisições, que é o que os portais pontuam como robô (ver `.claude/documentacaoantibot.md`).
Decidido em 23/09/2026.

### Tarefas

| # | Tarefa | Onde |
| --- | --- | --- |
| F1.1 | **Diagnóstico por portal**: salvar 1 HTML de cada portal (busca de referência) e anotar onde está a foto e quantas vêm por anúncio. Suspeitas a confirmar: JSON-LD `image` (VivaReal, Zap, ChavesNaMão, Mercado Livre, NetImóveis); payload RSC `medias`/`images` (Grupo ZAP — estender `rsc_grupozap.py`, que já faz join por `href`); `__NEXT_DATA__` (QuintoAndar, provavelmente só o id da imagem, precisa montar a URL do CDN); `<img data-src>` dos cards (ImovelWeb, OLX). | `scraper/*.py` |
| F1.2 | Helper `extrair_fotos(item) -> list[str]` em `parser.py`: aceita `str`, `list[str]`, `list[ImageObject]`, resolve URL relativa, troca placeholders de tamanho do CDN (ex.: `{width}x{height}` do Grupo ZAP), deduplica, limita a ~10. Com testes. | `scraper/parser.py`, `tests/test_fotos.py` |
| F1.3 | Usar o helper em cada scraper, preenchendo `registro['fotos']`. Um portal por commit. | `scraper/*.py` |
| F1.4 | Deduplicação cross-portal: ao fundir o mesmo imóvel de portais diferentes, **unir** as fotos em vez de manter só as do representante. | `services/deduplicador.py` |
| F1.5 | Diagnóstico: `DiagnosticoColeta.com_foto` (igual ao `com_coordenada`) — se um portal mudar o HTML e as fotos zerarem, aparece em vez de virar card sem imagem sem explicação. | `models.py`, `services/search.py` |
| F1.6 | **Carrossel no card**: área de imagem no topo do `ResultCard` (proporção fixa, 16:10), setas + contador "3/8" + swipe no touch, `loading="lazy"`, `referrerPolicy="no-referrer"`, `onError` pula a foto quebrada. Sem foto → **imagem genérica com selo visível "Foto ilustrativa"** (e `alt`/tooltip dizendo que o anúncio não tem foto), para nunca ser confundida com foto real do imóvel; o card continua. Sem lib nova. | `components/FotoCarrossel.tsx` (novo), `ResultCard.tsx` |
| F1.7 | Lightbox ao clicar na foto (tela cheia, setas do teclado, Esc fecha). | `components/FotoCarrossel.tsx` |
| ~~F1.8~~ | ~~Galeria completa sob demanda~~ — **descartada**: basta mostrar as fotos da listagem. | — |
| F1.9 | **Só se o hotlink falhar** no F1.1: proxy `GET /api/imagem?u=` com **allowlist de domínios dos portais** (senão é SSRF) e cache em disco. Não fazer se `referrerPolicy="no-referrer"` resolver. | `main.py` |
| F1.10 | Export: coluna "Foto (capa)" com a primeira URL. | `services/export.py` |

### Decisões tomadas

- **Anúncio sem foto aparece**, com imagem genérica claramente marcada como genérica. Não é
  descartado. O normal é todo anúncio vir com foto, então a imagem genérica deve ser exceção —
  se passar a ser comum num portal, é sinal de que a extração quebrou (o `com_foto` do F1.5
  mostra isso).
- **Sem galeria sob demanda**: só as fotos que vêm na página de resultados.

**Pronto quando:** na busca de referência (Fortaleza-CE, R$ 280k–500k, 2 quartos), ≥ 80% dos
cards com foto real (a imagem genérica é exceção); VivaReal/Zap com várias; carrossel funcionando em desktop e celular;
`pytest` e `npm run build` verdes.

---

## F2 — Filtro de banheiros (agente `filtro-banheiros`) — ✅ feito, exceto F2.3

**Situação hoje:** o campo `banheiros` já é coletado e exibido no card, mas não há filtro.

| # | Tarefa | Onde |
| --- | --- | --- |
| F2.1 | Select "Banheiros" no formulário, ao lado de "Quartos": Qualquer / 1 / 2 / 3 / 4+. | `components/SearchForm.tsx` |
| F2.2 | Filtro pós-coleta em `filtrar_anuncios`, seguindo o precedente de `quartos`: exato para 1–3, `>=` para 4; anúncio **sem** banheiros informado é mantido (mesma regra de quartos). Descarte conta como `banheiros_divergente` no diagnóstico. | `services/validacao.py` |
| F2.3 ⏳ | Filtro na origem onde o portal aceita (menos páginas desperdiçadas): verificar parâmetro de URL em VivaReal, Zap, ImovelWeb, ChavesNaMão. Onde não houver, o F2.2 cobre. | `scraper/*.py` |
| F2.4 | Chave do cache e histórico incluem `banheiros` (depende de F0). | `repositories/busca_repo.py` |
| F2.5 | Testes: exato, 4+, `None` mantido, diagnóstico conta o descarte, cache não mistura buscas com banheiros diferentes. | `tests/test_banheiros.py` |

**Pronto quando:** buscar com "2 banheiros" só traz cards com 2 (ou sem informação), o
diagnóstico diz quantos saíram, e repetir a busca sem o filtro não devolve o cache filtrado.

---

## F3 — Mapa / API de tiles (agente `mapa-tiles`)

**Situação hoje:** `Mapa.tsx` usa tiles raster da CARTO, que passou a exigir chave. A chave
vem de `VITE_CARTO_API_KEY` em `frontend/.env.local` e é **embutida no build**. Três jeitos
de quebrar:

1. Máquina sem `.env.local` → tile "API KEY REQUIRED".
2. `.env.local` criado **depois** do `npm run build` → o `dist/` servido pelo `.bat` continua
   sem chave.
3. `Dockerfile` roda `npm run build` sem `ARG VITE_CARTO_API_KEY` → no deploy o mapa sai
   sempre sem chave.

| # | Tarefa | Onde |
| --- | --- | --- |
| F3.1 | **Diagnóstico**: confirmar qual dos 3 casos é o seu (ou se é outro — cota, domínio não autorizado na CARTO, rede). | — |
| F3.2 | **Recomendado — proxy de tiles no backend**: `GET /api/tiles/{z}/{x}/{y}.png` lê `CARTO_API_KEY` do `.env` do **backend**, repassa para a CARTO e guarda em cache em disco. A chave sai do bundle JS (hoje qualquer um que abre o site a vê), muda sem rebuild e o cache reduz o consumo da cota. | `main.py`, `services/tiles.py` (novo), `.env.example` |
| F3.3 | **Fallback sem chave**: se o proxy responder erro (sem chave, cota estourada), trocar para um provedor sem chave (Esri World Dark Gray, ou OSM padrão com filtro CSS escuro) e mostrar aviso discreto no mapa em vez de tile quebrado. | `components/Mapa.tsx` |
| F3.4 | Deploy: incluir `CARTO_API_KEY` no `.env.deploy.example`; remover a dependência de build-arg. | `.env.deploy.example`, `Dockerfile` |
| F3.5 | Atualizar `COMO-RODAR.md` (a chave passa do `.env.local` do frontend para o `.env` do backend). | `COMO-RODAR.md` |

**Alternativa mais simples (se não quiser proxy):** só F3.3 + passar `ARG` no `Dockerfile` +
aviso no `.bat` quando o `dist/` foi gerado sem chave.

**Pronto quando:** o mapa carrega em máquina nova sem passo manual no frontend, no deploy
Docker, e degrada com aviso (não com "API KEY REQUIRED") quando a chave falha.

---

## F4 — Busca: mais sites e mais volume (agente `coleta-fontes`)

Continuação do `PROMPT_AGENTES_BUSCA.md`, com foco em volume e novas fontes. **Sempre**
começar pela skill `diagnosticar-scraper` — a tabela de volumes daquele documento é de agosto.

| # | Tarefa | Onde |
| --- | --- | --- |
| F4.1 | **Linha de base**: rodar `diagnosticar-scraper` em todos os 8 portais e registrar bruto por portal em `BASELINE.json`. Nada muda antes disso. | `BASELINE.json` |
| F4.2 | Consertar quem está devolvendo 0 hoje (candidatos: Mercado Livre, NetImóveis, QuintoAndar, OLX — confirmar no F4.1). Um portal por commit. | `scraper/*.py` |
| F4.3 | Paginação uniforme: todo scraper busca N páginas (teto configurável no `.env`) e para ao receber página vazia/repetida, respeitando o espaçamento anti-bot. | `scraper/*.py` |
| F4.4 | Busca por bairro nos portais que só o VivaReal faz hoje (Zap, ChavesNaMão) quando o usuário escolhe bairros — o recorte pós-coleta joga fora o que a paginação trouxe de outros bairros. | `scraper/*.py`, `services/search.py` |
| F4.5 | **Fontes novas** (skill `adicionar-fonte`), avaliar nesta ordem e implementar as viáveis: Wimóveis, 123i, Loft, Imóvel Guide, sites de construtoras concorrentes (Direcional, Cury, Tenda, Pacaembu — lançamentos com foto e planta, relevante para o comparativo MRV). Cada fonte nova **já extrai fotos** (helper do F1.2). | `scraper/<novo>.py`, `services/search.py`, `frontend/src/data/portais.ts` |
| F4.6 | Revisar o que descarta anúncio válido: medir `descartados_por_motivo` na busca de referência e ajustar a regra que mais corta sem motivo (refinador RF em amostra pequena, faixa de área, etc.). | `services/validacao.py`, `services/rf_refiner.py` |
| F4.7 | Relevância/ordenação: ordenar por proximidade do bairro pedido + completude do anúncio (tem foto, área, coordenada) + `rf_score`, em vez da ordem de chegada. | `services/search.py` |

**Pronto quando:** bruto da busca de referência sobe em relação ao `BASELINE.json` do F4.1,
com pelo menos 2 fontes novas funcionando e nenhum portal antigo regredindo.

---

## Regras para todos os agentes

- Rodar `pytest tests -q` (backend) e `npm run build` (frontend — roda `tsc`) antes de cada commit.
- Rodar a skill `validar-busca` ao final de cada frente.
- Nunca imprimir chaves (`SCRAPERAPI_KEY`, `CARTO_API_KEY`) em log, commit ou resposta.
- Não aumentar a frequência de requisições aos portais sem ler `.claude/documentacaoantibot.md`.
- Seguir o estilo do código: comentários em português explicando o **porquê**, como os que já existem.
