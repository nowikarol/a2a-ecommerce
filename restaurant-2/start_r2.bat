@echo off
title Uruchamianie Restauracji 2 (R2)

set PYTHON_EXE=python
set PYTHONPATH=%cd%

echo ============================================
echo   Inicjalizacja Wezla R2 (Restauracja 2)
echo ============================================

:: Czyszczenie procesow, ktore moga blokowac porty (8003 dla MCP, 8022 dla API)
echo [1/4] Czyszczenie zablokowanych portow...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8003') do taskkill /f /pid %%a 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8022') do taskkill /f /pid %%a 2>nul

:: Uruchomienie Serwera MCP jako modulu (-m)
echo [2/4] Uruchamianie Serwera MCP...
start "R2 - Serwer MCP" cmd /k "%PYTHON_EXE% -m network.server"

timeout /t 2 /nobreak >nul

:: Uruchomienie Agenta (Inicjalizacja bazy i nasluchiwanie API)
echo [3/4] Uruchamianie Agenta API...
start "R2 - Agent API" cmd /k "%PYTHON_EXE% Projekt_A2A.py"

timeout /t 2 /nobreak >nul

:: Uruchomienie interfejsu graficznego (Streamlit)
echo [4/4] Uruchamianie interfejsu GUI (Streamlit)...
start "R2 - GUI Panel" cmd /k "%PYTHON_EXE% -m streamlit run gui.py"

echo.
echo ============================================
echo   Gotowe! Wszystkie moduly R2 uruchomione.
echo ============================================