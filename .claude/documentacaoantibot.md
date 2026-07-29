# Estratégias Anti-Bot para Scraping de Portais Imobiliários (OLX, ZAP, VivaReal etc.)

> Documento de referência técnica para avaliação pelos agentes do PriceRadar Intelligence (Data Investigator, Frontend, Critic). Objetivo: decidir se e como incorporar estas técnicas ao pipeline de coleta de dados.

**Contexto do projeto:** PriceRadar Intelligence é uma plataforma de precificação imobiliária competitiva (FastAPI + React/Vite/TypeScript + Pandas + scikit-learn), com arquitetura multi-agente. O gargalo atual está na coleta de dados de portais com proteção anti-bot agressiva (OLX e similares).

---

## 1. Problema

Sites como OLX, ZAP Imóveis, VivaReal e QuintoAndar usam proteção anti-bot em múltiplas camadas (Cloudflare, DataDome, fingerprinting de browser e de rede). Scraping "cru" com `requests`/BeautifulSoup, ou até Selenium/Playwright sem tratamento, é bloqueado rapidamente. É necessário resolver o problema em camadas, não com uma única ferramenta.

---

## 2. Camadas de solução

### 2.1 Renderização/Stealth (evitar detecção de headless browser)

| Ferramenta | Uso recomendado | Observações |
|---|---|---|
| `playwright-stealth` (Python) | Baseline de evasão, cobre fingerprint checks básicos | Pacote Python mantido ativamente; a versão Node.js está defasada desde 2023 — usar a versão Python |
| `nodriver` | Padrão Python moderno para stealth | Fala direto com CDP, assíncrono, não usa WebDriver (um dos principais sinais de detecção) |
| `SeleniumBase` (modo UC) | Páginas com Cloudflare e CAPTCHA | Opção mais segura em Python para esse cenário específico |
| `Patchright` | Upgrade de stealth "drop-in" | Ideal se o código já usa Playwright — migração de baixo esforço |

**Limitação importante:** stealth plugins funcionam bem em sites com proteção leve, mas sistemas modernos (Cloudflare avançado, DataDome, Kasada) os detectam consistentemente. Não deve ser tratado como solução definitiva para OLX.

### 2.2 Camada de rede (TLS/fingerprint de conexão)

Bloqueios não acontecem só no nível JS — a assinatura TLS/TCP da requisição também é analisada.

| Ferramenta | Uso recomendado |
|---|---|
| `curl-cffi` | Requisições HTTP diretas quando não é necessário um browser completo (ex: endpoints XHR internos que o OLX expõe) |
| `Camoufox` | Fingerprinting difícil; mais lento, usar para alvos específicos, não para volume alto |

### 2.3 Serviços gerenciados (fallback quando DIY não compensa)

Custo de manter proxy pool + stealth + CAPTCHA solver in-house cresce rápido em volume. Serviços gerenciados podem ser usados como fallback (não como base 100%, por causa do custo por request):

- **Scrapfly Scrape API** — bypass de anti-bot via `asp=true` e renderização JS via `render_js=true`, chamadas HTTP simples, sem manter browser.
- **Scrapeless / Browserless (BQL)** — gerencia instâncias de browser, pools de proxy e CAPTCHAs automaticamente.
- **FlareSolverr** — self-hosted, resolve desafios Cloudflare especificamente e devolve a resposta para o scraper normal.

---

## 3. Arquitetura proposta para os agentes

### 3.1 Agente/módulo de "Acesso" (escalonamento progressivo)

```
1. Fetch direto (requests/httpx)          → rápido, barato
   ↓ (se 403/CAPTCHA)
2. Playwright + Patchright (stealth)      → intermediário
   ↓ (se ainda falhar)
3. API gerenciada (Scrapfly/FlareSolverr) → custo mais alto, alta taxa de sucesso
```

Isso evita usar a camada mais cara em todo request — só escala quando necessário.

### 3.2 Componentes adicionais recomendados

1. **Rotação de proxy residencial** (não datacenter) — IPs de datacenter são banidos rapidamente em portais grandes.
2. **Extração via LLM estruturado** em vez de regex/XPath fixo — envia HTML limpo (ou screenshot) para o agente Investigator/Critic pedindo saída em JSON estruturado. Resolve o problema de mudanças de layout, comum nesses sites.
3. **Rate limiting + jitter humano** — delays aleatórios (2-8s), scroll simulado, movimento de mouse. Reduz sinalização de bot mais eficazmente do que só trocar User-Agent.
4. **Cache de sessão/cookies** — manter sessão viva evita re-challenge constante.

---

## 4. Nota legal/estratégica

OLX e portais imobiliários costumam ter termos de uso que restringem scraping automatizado. Alguns oferecem APIs oficiais ou parcerias de dados. Antes de escalar para evasão pesada, vale avaliar:
- Existência de API oficial ou fonte de dados parceira (mais estável a longo prazo).
- Risco legal e de ToS de cada abordagem.
- Custo-benefício: serviços gerenciados vs. infraestrutura própria, considerando volume de dados necessário pelo PriceRadar.

---

## 5. Pontos em aberto para os agentes avaliarem

- [ ] Qual volume de requests/dia o Data Investigator precisa sustentar? (define se DIY compensa ou não)
- [ ] Orçamento disponível para API gerenciada (Scrapfly/Scrapeless) vs. custo de manter proxy pool próprio.
- [ ] Existe API oficial ou parceria de dados disponível para os portais-alvo?
- [ ] O pipeline de extração deve migrar de parsers fixos (XPath/regex) para extração via LLM estruturado?
- [ ] Qual nível de risco de bloqueio/legal é aceitável para o projeto?

---

*Fontes: pesquisa realizada em julho de 2026 sobre ferramentas anti-bot para scraping (Scrapfly, ZenRows, Scrapeless, AlterLab, Browserless).*