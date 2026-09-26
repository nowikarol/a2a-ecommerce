@echo off
title A2A Supply Chain Visualizer Overlay (:8080)
cd /d "%~dp0"
echo =========================================================================
echo Uruchamianie nakladki wizualizacji sieci A2A na http://localhost:8080
echo =========================================================================
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
pause
