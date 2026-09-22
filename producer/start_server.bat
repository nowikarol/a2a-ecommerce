@echo off
title Serwer MCP Producenta P1

set PYTHON_EXE=python

:: Czyszczenie procesow ktore moga blokowac port 8001
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001') do taskkill /f /pid %%a 2>nul

:: Tworzenie/aktualizacja bazy danych (bezpieczne przy wielokrotnym uruchomieniu)
echo Przygotowanie bazy danych producer.db...
%PYTHON_EXE% setup_db.py

:: Uruchomienie serwera MCP P1 na localhost:8001
echo Uruchamianie serwera MCP Producenta P1 (localhost:8001)...
%PYTHON_EXE% mcp_server.py

pause
