@echo off
setlocal
REM ============================================================
REM  PriceRadar - atualiza tudo e reinicia o backend.
REM
REM  Duplo clique depois de cada mudanca publicada na master:
REM    1. baixa o codigo novo (git pull na master)
REM    2. instala dependencias novas do backend e do frontend
REM    3. refaz o build do frontend (o link oficial serve o dist\)
REM    4. derruba o backend que estiver na porta 8002 e sobe de novo
REM    5. confere /api/health
REM
REM  Para no primeiro erro: um build quebrado nao pode derrubar o
REM  backend que esta funcionando.
REM ============================================================

cd /d "%~dp0"

echo.
echo [1/5] Baixando o codigo novo...
git checkout master || goto :erro
git pull --ff-only origin master || goto :erro

echo.
echo [2/5] Dependencias do backend...
if not exist "priceradar\backend\venv\Scripts\python.exe" (
    echo [ERRO] venv nao encontrado em priceradar\backend\venv
    goto :erro
)
priceradar\backend\venv\Scripts\python.exe -m pip install -q -r priceradar\backend\requirements.txt || goto :erro

REM A chave do mapa mudou de lugar: agora fica no .env do backend.
findstr /b /c:"CARTO_API_KEY=" priceradar\backend\.env >nul 2>&1
if errorlevel 1 (
    echo.
    echo [AVISO] CARTO_API_KEY nao esta em priceradar\backend\.env
    echo         O mapa vai abrir no modo alternativo. Copie o valor de
    echo         VITE_CARTO_API_KEY do priceradar\frontend\.env.local para
    echo         uma linha CARTO_API_KEY=... no .env do backend.
    echo.
)

echo.
echo [3/5] Build do frontend...
pushd priceradar\frontend
call npm install --no-audit --no-fund || (popd & goto :erro)
call npm run build || (popd & goto :erro)
popd

echo.
echo [4/5] Reiniciando o backend na porta 8002...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
timeout /t 2 /nobreak >nul

REM Se a tarefa agendada existe, e ela que sobe o backend (oculto, com log).
REM Senao, abre numa janela propria como o iniciar-priceradar.bat.
schtasks /query /tn "PriceRadar Backend" >nul 2>&1
if errorlevel 1 (
    start "PriceRadar" cmd /c "cd /d %~dp0priceradar\backend && venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --log-level info"
) else (
    schtasks /run /tn "PriceRadar Backend" >nul
)

echo.
echo [5/5] Conferindo se subiu...
set /a tentativas=0
:esperar
timeout /t 3 /nobreak >nul
set /a tentativas+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://localhost:8002/api/health -TimeoutSec 3).StatusCode } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto :ok
if %tentativas% lss 10 goto :esperar
echo [ERRO] O backend nao respondeu em 30s. Veja priceradar\backend\uvicorn_err.log
goto :erro

:ok
echo.
echo  ================================================
echo   PriceRadar atualizado e no ar (porta 8002).
echo   O link oficial ja serve a versao nova.
echo  ================================================
echo.
pause
exit /b 0

:erro
echo.
echo [FALHOU] Nada foi reiniciado depois do erro acima.
echo.
pause
exit /b 1
