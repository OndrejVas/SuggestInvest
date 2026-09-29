@echo off
title Interactive Brokers - Client Portal Gateway
color 0A
echo =====================================================================
echo  Interactive Brokers Client Portal Gateway (SuggestInvest Bridge)
echo =====================================================================
echo.

set "JAVA_DIR=C:\Program Files\Eclipse Adoptium\jre-17.0.20.101-hotspot\bin"
if exist "%JAVA_DIR%\java.exe" set "PATH=%JAVA_DIR%;%PATH%"

where java >nul 2>&1
if errorlevel 1 (
    echo [CHYBA] Java nebyla nalezena v ceste PATH!
    echo Prosim overte instalaci Java Runtime Environment.
    echo.
    pause
    exit /b 1
)

echo [OK] Java 17 je pripravena.
echo [INFO] Spoustim Client Portal Gateway na portu 5000...
echo [INFO] Po zobrazeni "Server listening on port 5000"
echo        otevrete v prohlizeci odkaz: https://localhost:5000/
echo.

cd /d "%~dp0IB Gateway"
call bin\run.bat root\conf.yaml

echo.
echo Gateway byla ukoncena.
pause
