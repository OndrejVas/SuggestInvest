@echo off
chcp 65001 >nul
title SuggestInvest • Master Launcher (Gateway + AutoInvest)
color 0A

echo =====================================================================
echo  🚀 SuggestInvest • Spuštění kompletního autonomního ekosystému
echo =====================================================================
echo.

:: 1. Kontrola, zda běží IB Gateway na portu 7497
netstat -ano | findstr ":7497 " >nul 2>&1
if errorlevel 1 (
    echo [1/2] IB Gateway na portu 7497 neběží. Spouštím IB Gateway...
    start "IBKR Gateway" cmd /c "call start_ib_gateway.bat"
    echo Čekám 8 sekund na inicializaci brány...
    timeout /t 8 /nobreak >nul
) else (
    echo [1/2] ✅ IB Gateway již běží na portu 7497.
)

:: 2. Spuštění IBKR Live Sync v samostatném okně
echo [2/2] Spouštím IBKR Live Sync Service v samostatném okně...
start "IBKR Sync Service" cmd /c "call start_ibkr_sync.bat"

echo.
echo =====================================================================
echo ✅ HOTOVO! Obě okna (IBKR Gateway i AutoInvest Engine) běží.
echo =====================================================================
echo.
pause
