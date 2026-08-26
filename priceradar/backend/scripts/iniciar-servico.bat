@echo off
REM ============================================================
REM  PriceRadar - inicio silencioso para o Agendador de Tarefas.
REM
REM  Diferenca do iniciar-priceradar.bat da raiz: nao abre navegador
REM  (ninguem esta olhando no momento do login) e manda a saida para
REM  arquivo de log em vez de uma janela, porque roda oculto (via
REM  iniciar-servico-oculto.vbs).
REM ============================================================

cd /d "%~dp0..\"

if not exist "venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado em priceradar\backend\venv >> uvicorn_err.log
    exit /b 1
)

venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --log-level info >> uvicorn.log 2>> uvicorn_err.log
