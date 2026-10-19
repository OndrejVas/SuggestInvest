@echo off
chcp 65001 >nul
title SuggestInvest - IBKR Master Server & Live Sync (Port 8000 & 7497)
color 0A
echo =====================================================================
echo  SuggestInvest - IBKR Trading Server & Auto-Gateway Engine
echo =====================================================================
echo.
echo [1/2] Spoustim autonomni IBKR Watchdog a Gateway na pozadi...
start "" /b python "%~dp0IBKR-Demo-online\watchdog.py"
timeout /t 3 /nobreak >nul

echo [2/2] Spoustim SuggestInvest Master Server (API port 8000 + Live Sync)...
python server.py
pause
