@echo off
title Uruchamianie calego systemu A2A/MCP

echo ============================================
echo   Startowanie 5 serwerow (P1, R1, R2, H1, H2)
echo ============================================

:: Sciezka bazowa - katalog, w ktorym znajduje sie ten .bat
set BASE_DIR=%~dp0

:: --- P1: Producent (port 8001) ---
echo Uruchamianie P1 (Producent, :8001)...
start "P1 - Producent (8001)" cmd /k "cd /d %BASE_DIR%producer && start_server.bat"

timeout /t 1 /nobreak >nul

:: --- R1: Restauracja 1 (port 8002) ---
echo Uruchamianie R1 (Restauracja 1, :8002)...
start "R1 - Restauracja1 (8002)" cmd /k "cd /d %BASE_DIR%restaurant-1 && python main.py"

timeout /t 1 /nobreak >nul

:: --- R2: Restauracja 2 (port 8003) ---
:: TODO: potwierdzic prawdziwy plik startowy (main.py? Projekt_A2A.py? network/server.py?)
echo Uruchamianie R2 (Restauracja 2, :8003)...
start "R2 - Restauracja2 (8003)" cmd /k "cd /d %BASE_DIR%restaurant-2 && python Projekt_A2A.py"

timeout /t 1 /nobreak >nul

:: --- H1: Magazyn 1 (port 8004, potwierdzone z README) ---
echo Uruchamianie H1 (Magazyn 1, :8004)...
start "H1 - Magazyn1 (8004)" cmd /k "cd /d %BASE_DIR%warehouse-1 && python main.py"

timeout /t 1 /nobreak >nul

:: --- H2: Magazyn 2 (port 8005) ---
:: TODO: potwierdzic prawdziwy plik startowy (server.py? a2a.py? agent.py?)
echo Uruchamianie H2 (Magazyn 2, :8005)...
start "H2 - Magazyn2 (8005)" cmd /k "cd /d %BASE_DIR%warehouse-2 && python server.py"

echo.
echo Wszystkie 5 okien zostalo uruchomionych.
echo Zamknij to okno lub nacisnij dowolny klawisz, aby zakonczyc.
pause >nul