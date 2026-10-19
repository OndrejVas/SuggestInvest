@echo off
chcp 65001 >nul
title SuggestInvest • Interactive Brokers Gateway Watchdog & Sync Daemon
echo =====================================================================
echo 🤖 SuggestInvest • IBKR Gateway Watchdog & Live Sync Daemon (Port 7497)
echo =====================================================================
echo Dohledový proces nad IB Gateway (Port 7497 Socket API).
echo Synchronizace reálných pozic a hotovosti každých 30 sekund.
echo.

python ib_watchdog.py --interval 30

pause
