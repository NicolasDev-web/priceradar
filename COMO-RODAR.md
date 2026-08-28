# Como rodar o PriceRadar

Todos os comandos são para **PowerShell no Windows**, a partir da raiz do repositório
(`C:\Users\Nicolas\Documents\PrecificacaoBruninho`).

---

## O jeito normal: um duplo clique

```text
iniciar-priceradar.bat
```

Sobe tudo numa porta só (**8002**), mostra o IP da máquina na rede e abre o navegador.
É o que você usa no dia a dia. Para encerrar, feche a janela.

O `.bat` serve o **frontend já compilado** (`priceradar/frontend/dist`). Se você mexeu no
frontend, rode o build antes — senão continua vendo a versão antiga:

```powershell
cd priceradar\frontend; npm run build
```

---

## Desenvolvimento (dois processos)

Use quando estiver **editando o frontend** e quiser hot reload. São duas janelas.

**Janela 1 — backend com reload automático:**

```powershell
cd priceradar\backend; venv\Scripts\python.exe -m uvicorn main:app --reload --port 8002
```

**Janela 2 — frontend em modo dev:**

```powershell
cd priceradar\frontend; npm run dev
```

Abra <http://localhost:5173> (não a 8002). O Vite lê `.env.development`, que aponta a API
para `http://localhost:8002`.

> Em modo dev o acesso é só por `localhost`. Para outra pessoa na rede alcançar, use o `.bat`.

---

## Testes

```powershell
cd priceradar\backend; venv\Scripts\python.exe -m pytest tests -q
```

Rápido (~3s) e sem rede. Rode antes de commitar.

Um arquivo só, ou um teste só:

```powershell
cd priceradar\backend; venv\Scripts\python.exe -m pytest tests\test_geo.py -q
cd priceradar\backend; venv\Scripts\python.exe -m pytest tests -q -k "acento"
```

O build do frontend também é uma verificação — `npm run build` roda `tsc` antes do Vite,
então erro de tipo aparece ali.

---

## Primeira vez numa máquina nova

```powershell
# Backend
cd priceradar\backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env

# Frontend
cd ..\frontend
npm install
echo VITE_CARTO_API_KEY=cole-aqui-a-chave-gratuita > .env.local
npm run build
```

O `.env` **não** é versionado. O `.env.example` documenta cada variável com o motivo do
valor padrão — vale ler antes de mudar qualquer coisa. Só a `SCRAPERAPI_KEY` fica em
branco (opcional: é o nível 2 de acesso, usado só quando o direto falha).

O `.env.local` do frontend também não é versionado — é onde fica a `VITE_CARTO_API_KEY`,
a chave (gratuita) que o mapa usa para buscar os tiles escuros. Sem ela, o mapa some
os quarteirões e mostra "API KEY REQUIRED" por cima. Gere a sua em
[carto.com/basemaps/apikey](https://carto.com/basemaps/apikey) (só e-mail e domínio,
sem cartão).

O banco (`priceradar.db`) e as migrações se criam sozinhos ao subir o servidor.

---

## Acesso pela rede local

O `.bat` já sobe com `--host 0.0.0.0` e imprime o endereço. Se precisar do IP na mão:

```powershell
ipconfig | Select-String IPv4
```

Duas coisas que costumam travar:

- **Firewall do Windows** pede autorização na primeira vez. Tem que liberar.
- O **mapa busca os tiles na internet** (OpenStreetMap via CARTO). Numa rede isolada, os
  pinos aparecem mas o fundo fica preto — os dados continuam certos.

---

## Atalhos úteis

| O quê | Comando |
| --- | --- |
| Só a API, sem abrir navegador | `cd priceradar\backend; venv\Scripts\python.exe -m uvicorn main:app --port 8002` |
| Dados fictícios, sem rede | Ponha `MOCK=true` no `.env` e reinicie |
| Ver se a API respondeu | `curl http://localhost:8002/api/health` |
| Bairros conhecidos de uma cidade | `curl "http://localhost:8002/api/bairros?cidade=Fortaleza,%20CE"` |
| Limpar o cache de buscas | Apague `priceradar\backend\priceradar.db` (recriado no próximo start) |
| Refazer a lista de cidades | `cd priceradar\backend; venv\Scripts\python.exe scripts\gerar_cidades.py` |

**Porta 8002 ocupada** (sobrou um servidor de antes):

```powershell
Get-NetTCPConnection -LocalPort 8002 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## Deploy

Ainda não há nada publicado. O que existe é a preparação — e uma medição que
precisa ser feita antes de escolher onde hospedar.

### A pergunta que decide tudo

A coleta é gratuita porque o `curl-cffi` imita a assinatura TLS do Chrome. Os
portais bloqueiam por TLS, não por User-Agent — mas também podem pontuar por
reputação de ASN, e as faixas de nuvem (Oracle, AWS, GCP) entram com nota baixa.
Se o acesso direto cair num IP de datacenter, a coleta passa a depender da
ScraperAPI: 1.000 créditos/mês no plano grátis, ~40 buscas. Isso muda a
arquitetura, então é para medir:

```powershell
# 1. Aqui, para ter a linha de base (já rodado em 17/08/2026 — ver
#    priceradar\backend\data\sonda-baseline-local.json)
cd priceradar\backend; venv\Scripts\python.exe scripts\sonda_acesso.py --json base.json

# 2. Na VM da nuvem, no mesmo dia
python scripts/sonda_acesso.py --json nuvem.json

# 3. Compare
python scripts/sonda_acesso.py --comparar base.json nuvem.json
```

Custa 4 requisições e não gasta crédito de proxy. Linha de base de 17/08/2026,
Fortaleza-CE R$ 280k-500k 2 quartos: vivareal 30, zapimoveis 30, chavesnamao 15,
imovelweb 27 — todos em 200.

### As duas trilhas

**Se os 4 portais responderem na nuvem** → VM ARM Always Free da Oracle. É o
único free tier que aguenta os ~340 MB de dependências mais o Chromium, fica
sempre ligado e tem disco persistente, então o SQLite continua como está. Os
arquivos já estão prontos na raiz: `Dockerfile`, `docker-compose.yml`,
`Caddyfile` e `.env.deploy.example`. Na VM:

```bash
cp .env.deploy.example .env      # preencha DOMINIO, USUARIO e SENHA_HASH
docker compose up -d --build
```

O Caddy resolve HTTPS e a autenticação na borda — a aplicação não tem login
próprio. Atualizar depois: `git pull && docker compose up -d --build`.

**Se algum portal cair para 403** → a coleta fica na rede interna. O acesso
remoto se resolve com Tailscale (plano grátis cobre 6 usuários): instale nesta
máquina e nos notebooks, e a URL passa a funcionar de qualquer lugar sem expor
nada na internet pública. Nesse caso vale transformar o `.bat` em serviço do
Windows, para sobreviver a reboot.

---

## Onde ficam as coisas

```text
priceradar/backend/
  main.py              rotas da API
  services/search.py   orquestra a busca
  scraper/             um arquivo por portal
  data/                caches em disco (não versionados)
  .env                 configuração — não versionado
  venv/                ambiente virtual

priceradar/frontend/
  src/components/      a UI
  dist/                build servido pelo .bat — regerar após editar
```

Dois documentos vizinhos: `RESUMO_PROJETO.md` (estado do projeto, fica só na máquina) e
`.claude/documentacaoantibot.md` (por que a coleta é espaçada do jeito que é).
