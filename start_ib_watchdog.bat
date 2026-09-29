@echo off
chcp 65001 >nul
title SuggestInvest • Interactive Brokers Gateway Watchdog & Keep-Alive Daemon
echo =====================================================================
echo 🤖 SuggestInvest • IBKR Gateway Watchdog & Auto-Reconnect Daemon
echo =====================================================================
echo Spouštím dohledový proces nad https://localhost:5000...
echo Keep-Alive pingy poběží každých 60 sekund.
echo.

python ib_watchdog.py --interval 60

pause
