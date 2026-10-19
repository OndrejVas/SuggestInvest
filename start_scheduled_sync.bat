@echo off
chcp 65001 >nul
title SuggestInvest • GitHub Scheduled Telemetry Sync (09:00, 12:00, 15:00, 18:00, 21:00 CET)
color 0B

echo =====================================================================
echo 🌐 SuggestInvest • GitHub Scheduled Sync Daemon
echo =====================================================================
echo Synchronizace Central Hub a podstránek na https://ondrejvas.github.io/SuggestInvest/
echo.
echo Harmonogram aktualizací (CET):
echo   • 09:00 CET (Otevření evropských trhů)
echo   • 12:00 CET (Polední rebalancování)
echo   • 15:00 CET (Předobchodní fáze US trhů)
echo   • 18:00 CET (Hlavní seance US & komodit)
echo   • 21:00 CET (Závěr US trhů a noční shrnutí)
echo.
echo Zabezpečení:
echo   • Všechny HTML stránky chráněny SHA-256 heslem
echo   • Přihlašovací údaje IBKR (IBKR-Demo-online, .key, .pem) VYLOUČENY
echo   • Rebase z origin/main pro soulad s GitHub Actions
echo =====================================================================
echo.

python scripts/git_scheduled_sync.py

pause
