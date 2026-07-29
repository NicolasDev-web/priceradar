@echo off
REM ============================================================
REM  PriceRadar - inicia a aplicacao e abre no navegador.
REM
REM  --host 0.0.0.0 faz o servidor aceitar conexoes da rede.
REM  Sem isso ele so escuta em 127.0.0.1 e mais ninguem alcanca.
REM  Para fechar, feche esta janela (ou Ctrl+C).
REM ============================================================

cd /d "%~dp0priceradar\backend"

if not exist "venv\Scripts\python.exe" (
    echo.
    echo [ERRO] Ambiente virtual nao encontrado em priceradar\backend\venv
    echo Rode: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "..\frontend\dist\index.html" (
    echo.
    echo [AVISO] Build do frontend nao encontrado - so a API vai subir.
    echo Para gerar: cd priceradar\frontend ^&^& npm run build
    echo.
)

REM Descobre o IP desta maquina para informar ao colega.
echo.
echo  ================================================
echo   PriceRadar iniciando...
echo.
echo   Nesta maquina:  http://localhost:8002
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%j in ("%%i") do echo   Na rede:        http://%%j:8002
)
echo.
echo   Feche esta janela para encerrar.
echo  ================================================
echo.

REM Abre o navegador depois de dar tempo do servidor subir.
start "" /b cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:8002"

venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --log-level info
