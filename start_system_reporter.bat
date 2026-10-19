@echo off
chcp 65001 >nul
title SuggestInvest • System Reporting & Resource Monitor Daemon
echo =====================================================================
echo 📊 SuggestInvest • System Reporting & Cloud VPS Resource Monitor
echo =====================================================================
echo Dohled nad CPU, RAM, síťovým provozem, procesy a integritou dat.
echo Ukládání snapshotů do: data/system_report.json
echo Časová řada v:        data/system_telemetry_history.jsonl
echo Logování do:           logs/system_reporter.log
echo.
echo Režim: Kontinuální periodický dohled (každých 10 sekund)
echo Pro ukončení stiskněte Ctrl+C.
echo =====================================================================
echo.

python system_reporter.py --interval 10

pause
