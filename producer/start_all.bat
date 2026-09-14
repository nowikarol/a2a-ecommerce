@echo off
title Launcher Serwerow Fabryki

set PYTHON_EXE="C:\Users\vonix\AppData\Local\Programs\Python\Python314\python.exe"

:: 1. Czyszczenie zablokowanych procesow ngrok oraz procesow na porcie 8000
echo Czyszczenie starych procesow...
taskkill /f /im ngrok.exe 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do taskkill /f /pid %%a 2>nul

if exist ngrok_url.txt del ngrok_url.txt

:: 2. Uruchomienie Serwera MCP (Port 8000)
echo [1/2] Uruchamianie Serwera MCP (Port 8000)...
start "Serwer MCP (FastMCP SSE - Port 8000)" cmd /k "%PYTHON_EXE% mcp_server.py"

:: Wydluzony czas startu (5 sek), aby MCP zdazyl wstac
timeout /t 5 /nobreak > nul

:: 3. Uruchomienie Agenta i Tunelu
echo [2/2] Uruchamianie Agenta A2A i tworzenie tunelu Ngrok dla MCP...
start "Agent A2A (FastAPI + Ngrok)" cmd /k "%PYTHON_EXE% agent_server.py"

echo Oczekiwanie na wygenerowanie adresu publicznego...

:WAIT_LOOP
timeout /t 1 /nobreak > nul
if not exist ngrok_url.txt goto WAIT_LOOP

echo.
echo =======================================================================
echo  GOTOWY ADRES SERWERA MCP DO WYSŁANIA KOLEDZE:
echo =======================================================================
type ngrok_url.txt
echo.
echo =======================================================================
echo  [INFO] Adres zostal rowniez automatycznie skopiowany do schowka!
echo         Mozesz od razu uzyc Ctrl + V w komunikatorze.
echo =======================================================================
echo.
pause