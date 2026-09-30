@echo off
chcp 65001 >nul
title SuggestInvest • Master Launcher (Gateway + AutoInvest)
color 0A

echo =====================================================================
echo  🚀 SuggestInvest • Spuštění kompletního autonomního ekosystému
echo =====================================================================
echo.

:: 1. Kontrola, zda běží Gateway na portu 5000
netstat -ano | findstr ":5000 " >nul 2>&1
if errorlevel 1 (
    echo [1/2] Gateway neběží. Spouštím IB Gateway v novém okně...
    start "IBKR Gateway" cmd /c "call start_ib_gateway.bat"
    echo Čekám 8 sekund na inicializaci brány...
    timeout /t 8 /nobreak >nul
) else (
    echo [1/2] ✅ IBKR Gateway již běží na portu 5000.
)

:: 2. Spuštění AutoInvest Engine v samostatném okně
echo [2/2] Spouštím AutoInvest Engine v samostatném okně...
start "AutoInvest Engine" cmd /c "call start_autoinvest.bat"

echo.
echo =====================================================================
echo ✅ HOTOVO! Obě okna (IBKR Gateway i AutoInvest Engine) běží.
echo =====================================================================
echo.
pause
