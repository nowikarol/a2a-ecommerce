@echo off
setlocal enabledelayedexpansion
title Zatrzymywanie ekosystemu A2A
echo ==========================================================
echo   Zatrzymywanie procesow ekosystemu A2A
echo ==========================================================

set PORTS=8001 8002 8003 8004 8005 8022 8080
set FOUND=0

for %%p in (%PORTS%) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":%%p " ^| findstr LISTENING') do (
        echo Zatrzymywanie procesu PID %%a na porcie %%p
        taskkill /f /pid %%a >nul 2>&1
        set FOUND=1
    )
)

echo.
if "!FOUND!"=="0" (
    echo Zaden proces nie nasluchiwal na portach ekosystemu.
) else (
    echo Wszystkie serwery powiazane z portami zostaly zatrzymane.
)
echo ==========================================================
echo.
pause
