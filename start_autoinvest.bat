@echo off
chcp 65001 >nul
title SuggestInvest • AutoInvest Executor & Real Demo Engine
color 0B
echo =====================================================================
echo  🤖 SuggestInvest • AutoInvest Executor & Real Demo Rotation Engine
echo =====================================================================
echo.
echo 1. Kontroluji stav IBKR Gateway (https://localhost:5000)...
python autoinvest_executor.py
echo.
echo =====================================================================
echo Vyberte akci:
echo [1] Spustit okamžitou reálnou exekuci nákupního koše (5 titulů)
echo [2] Spustit trvalý sledovač a automatický Rotation Engine (TP/SL dohled)
echo [3] Pouze provést kontrolu stavu účtu
echo =====================================================================
set /p choice="Zadejte volbu [1/2/3]: "

if "%choice%"=="1" (
    echo.
    echo 🚀 Spouštím exekuci koše...
    python autoinvest_executor.py --execute
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

pause
