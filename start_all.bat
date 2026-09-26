@echo off
title Ekosystem A2A Supply Chain & Visualizer
set BASE_DIR=%~dp0

echo ==========================================================
echo   Uruchamianie ekosystemu A2A Supply Chain & Visualizer
echo ==========================================================

:: Sprawdzenie wirtualnego srodowiska venv
set VENV_ACTIVATE=
if exist "%BASE_DIR%venv\Scripts\activate.bat" (
    echo Wykryto wirtualne srodowisko: venv
    set VENV_ACTIVATE=call "%BASE_DIR%venv\Scripts\activate.bat" ^&^& 
) else if exist "%BASE_DIR%.venv\Scripts\activate.bat" (
    echo Wykryto wirtualne srodowisko: .venv
    set VENV_ACTIVATE=call "%BASE_DIR%.venv\Scripts\activate.bat" ^&^& 
)

:: 1. Producent P1 (port 8001)
echo [1/7] Uruchamianie Producent P1 (:8001)...
start "P1: Producent (:8001)" cmd /k "cd /d %BASE_DIR%producer && %VENV_ACTIVATE%python MCP_server.py"
timeout /t 1 /nobreak >nul

:: 2. Hurtownia H1 (port 8004)
echo [2/7] Uruchamianie Hurtownia H1 (:8004)...
start "H1: Hurtownia 1 (:8004)" cmd /k "cd /d %BASE_DIR%warehouse-1 && %VENV_ACTIVATE%python main.py"
timeout /t 1 /nobreak >nul

:: 3. Hurtownia H2 (port 8005)
echo [3/7] Uruchamianie Hurtownia H2 (:8005)...
start "H2: Hurtownia 2 (:8005)" cmd /k "cd /d %BASE_DIR%warehouse-2 && %VENV_ACTIVATE%python server.py"
timeout /t 1 /nobreak >nul

:: 4. Restauracja R1 (port 8002)
echo [4/7] Uruchamianie Restauracja R1 (:8002)...
start "R1: Restauracja 1 (:8002)" cmd /k "cd /d %BASE_DIR%restaurant-1 && %VENV_ACTIVATE%python main.py"
timeout /t 1 /nobreak >nul

:: 5. Restauracja R2 - Serwer MCP (port 8003)
echo [5/7] Uruchamianie Restauracja R2 MCP (:8003)...
start "R2: Serwer MCP (:8003)" cmd /k "cd /d %BASE_DIR%restaurant-2 && set PYTHONPATH=%BASE_DIR%restaurant-2 && %VENV_ACTIVATE%python -m network.server"
timeout /t 1 /nobreak >nul

:: 6. Restauracja R2 - Agent LangGraph (port 8022)
echo [6/7] Uruchamianie Restauracja R2 Agent (:8022)...
start "R2: Agent LangGraph (:8022)" cmd /k "cd /d %BASE_DIR%restaurant-2 && %VENV_ACTIVATE%python Projekt_A2A.py"
timeout /t 1 /nobreak >nul

:: 7. Nakladka Wizualizatora WWW (port 8080)
echo [7/7] Uruchamianie Nakladka Wizualizatora (:8080)...
start "Overlay: Wizualizator (:8080)" cmd /k "cd /d %BASE_DIR%overlay && %VENV_ACTIVATE%python -m uvicorn app:app --host 0.0.0.0 --port 8080"

echo.
echo ==========================================================
echo   Wszystkie serwisy zostaly pomyslnie zainicjowane!
echo   Otworz w przegladarce: http://localhost:8080
echo ==========================================================
echo.
echo Aby zatrzymac wszystkie serwisy, uruchom: stop_all.bat
echo.
pause