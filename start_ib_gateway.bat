@echo off
title Interactive Brokers - IB Gateway 1051
color 0A
echo =====================================================================
echo  Interactive Brokers - IB Gateway Standalone (Port 7497)
echo =====================================================================
echo.

if exist "C:\Jts\ibgateway\1051\ibgateway.exe" (
    echo [INFO] Spoustim oficialni IB Gateway z C:\Jts\ibgateway\1051...
    start "" "C:\Jts\ibgateway\1051\ibgateway.exe"
    echo [OK] IB Gateway byla spustena na portu 7497.
) else (
    echo [VAROVANI] IB Gateway nebyla nalezena v C:\Jts\ibgateway\1051\ibgateway.exe.
    pause
)

