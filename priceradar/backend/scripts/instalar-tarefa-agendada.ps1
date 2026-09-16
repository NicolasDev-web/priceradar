# ============================================================
#  PriceRadar - (re)instala a Tarefa Agendada do Windows que
#  sobe o backend automaticamente a cada logon.
#
#  Roda "schtasks /delete" (se ja existir) seguido de
#  "schtasks /create", sempre apontando para o proprio repositorio
#  onde este script vive (resolvido via $PSScriptRoot), entao
#  funciona mesmo se o clone estiver em outro caminho/maquina.
#
#  Uso: clique com o botao direito > "Executar com o PowerShell",
#  ou rode manualmente:
#    powershell -ExecutionPolicy Bypass -File instalar-tarefa-agendada.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$taskName = "PriceRadar Backend"
$vbsPath = Join-Path $PSScriptRoot "iniciar-servico-oculto.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "Nao encontrei $vbsPath - rode este script de dentro do repositorio."
    exit 1
}

Write-Host "Repo detectado: $PSScriptRoot"
Write-Host "Acao da tarefa: wscript.exe `"$vbsPath`""

# Remove a tarefa anterior, se existir. "Nao existe" nao e erro fatal aqui.
try {
    schtasks /delete /tn $taskName /f 2>$null | Out-Null
} catch {}

$create = schtasks /create /tn $taskName `
    /tr "wscript.exe `"$vbsPath`"" `
    /sc onlogon `
    /rl limited `
    /f

if ($LASTEXITCODE -ne 0) {
    Write-Error "Falha ao criar a tarefa agendada."
    exit 1
}

Write-Host ""
Write-Host "Tarefa '$taskName' instalada com sucesso."
Write-Host "Ela vai subir o backend (porta 8002) automaticamente no proximo logon."
Write-Host "Logs em: $PSScriptRoot\..\uvicorn.log e uvicorn_err.log"
Write-Host ""
Write-Host "Para rodar agora sem esperar o proximo logon:"
Write-Host "  schtasks /run /tn `"$taskName`""
