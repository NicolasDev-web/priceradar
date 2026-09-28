# Skill: validar-busca

Gate de validação obrigatório. Dispara a busca de referência no backend e
reporta contagem por portal, antes/depois de dedup e refinamento RF.

## Como usar

```
/validar-busca
```

## O que fazer

1. Verifica se o backend está rodando em `localhost:8002`:

```powershell
try { Invoke-RestMethod http://localhost:8002/api/health -TimeoutSec 3 }
catch { "backend não encontrado" }
```

2. Se não estiver rodando, sobe com:

```powershell
Start-Process -NoNewWindow -FilePath "priceradar\backend\venv\Scripts\python.exe" `
  -ArgumentList "-m", "uvicorn", "main:app", "--port", "8002", "--log-level", "info" `
  -WorkingDirectory "priceradar\backend"
Start-Sleep -Seconds 5
```

3. Dispara a busca de referência:

```powershell
$body = '{"cidade":"Fortaleza, CE","preco_min":280000,"preco_max":500000,"quartos":2}'
$resp = Invoke-RestMethod -Uri "http://localhost:8002/api/buscar" `
  -Method POST -Body $body -ContentType "application/json" -TimeoutSec 120
$resp | ConvertTo-Json -Depth 3
```

4. Reporte:
   - Total bruto (antes de dedup)
   - Total após dedup por URL
   - Total após dedup cross-portal
   - Total após RF Refiner
   - Tempo total em segundos
   - Contagem por portal
   - Comparação com baseline anterior (se houver)

5. Confirma que `MOCK=true` ainda funciona:

```powershell
$env:MOCK = "true"
# Re-dispara a busca e verifica se retorna 12 resultados mock
```

## Critério de sucesso

Total de empreendimentos válidos > baseline anterior (~2 após refinamento).
Nenhum scraper deve travar a busca (timeout máximo 120s total).
