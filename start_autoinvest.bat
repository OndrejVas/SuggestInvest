@echo off
chcp 65001 >nul
title SuggestInvest • AutoInvest Service & Aggressive Rotation Engine
color 0B
echo =====================================================================
echo  🤖 SuggestInvest • AutoInvest Service & Aggressive Rotation Engine
echo =====================================================================
echo.
echo 1. Kontroluji stav IBKR Gateway (https://localhost:5000)...
echo.
echo =====================================================================
echo Vyberte režim spuštění:
echo [1] Spustit kompletní službu (REST API port 5001 + Watchdog ležáků + Web UI) [DOPORUČENO]
echo [2] Spustit trvalý Watcher v terminálu (autoinvest_executor.py --watch)
echo [3] Spustit okamžitou exekuci nákupního koše (autoinvest_executor.py --execute)
echo [4] Pouze zkontrolovat stav účtu u brokera
echo =====================================================================
set /p choice="Zadejte volbu [1/2/3/4] (výchozí 1): "

if "%choice%"=="" set choice=1

if "%choice%"=="1" (
    echo.
    echo 🚀 Spouštím AutoInvest REST Service & Aggressive Rotation Engine...
    python autoinvest_service.py
    pause
    exit /b
)

if "%choice%"=="2" (
    echo.
    echo 🔄 Spouštím trvalý Watcher & Rotation Engine...
    python autoinvest_executor.py --watch
    pause
    exit /b
)

if "%choice%"=="3" (
    echo.
    echo 🚀 Spouštím exekuci koše...
    python autoinvest_executor.py --execute
    pause
    exit /b
)

if "%choice%"=="4" (
    echo.
    echo 🔍 Kontrola stavu účtu...
    python autoinvest_executor.py
    pause
    exit /b
)

pause

