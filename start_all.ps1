# =============================================================================
# A2A Supply Chain - Skrypt uruchomieniowy (start_all.ps1)
# Uruchamia wszystkie serwery ekosystemu w osobnych oknach PowerShell
# =============================================================================

$root = $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Uruchamianie ekosystemu A2A Supply Chain & Visualizer  " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Producent P1 (port 8001)
Write-Host "[1/7] Uruchamianie Producent P1 (:8001)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'P1: Producent (:8001)'; cd '$root\producer'; python MCP_server.py"

# 2. Hurtownia H1 (port 8004)
Write-Host "[2/7] Uruchamianie Hurtownia H1 (:8004)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'H1: Hurtownia 1 (:8004)'; cd '$root\warehouse-1'; python main.py"

# 3. Hurtownia H2 (port 8005)
Write-Host "[3/7] Uruchamianie Hurtownia H2 (:8005)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'H2: Hurtownia 2 (:8005)'; cd '$root\warehouse-2'; python server.py"

# 4. Restauracja R1 (port 8002)
Write-Host "[4/7] Uruchamianie Restauracja R1 (:8002)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'R1: Restauracja 1 (:8002)'; cd '$root\restaurant-1'; python main.py"

# 5. Restauracja R2 - Serwer MCP & Baza (port 8003)
Write-Host "[5/7] Uruchamianie Restauracja R2 MCP (:8003)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'R2: Serwer MCP (:8003)'; cd '$root\restaurant-2'; `$env:PYTHONPATH='$root\restaurant-2'; python -m network.server"

# 6. Restauracja R2 - Agent LangGraph (port 8022)
Write-Host "[6/7] Uruchamianie Restauracja R2 Agent LangGraph (:8022)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'R2: Agent LangGraph (:8022)'; cd '$root\restaurant-2'; python Projekt_A2A.py"

# 7. Nakładka Wizualizatora WWW (port 8080)
Write-Host "[7/7] Uruchamianie Nakładki Wizualizatora (:8080)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Overlay: Wizualizator (:8080)'; cd '$root\overlay'; python -m uvicorn app:app --host 0.0.0.0 --port 8080"

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Wszystkie serwisy zostaly pomyslnie zainicjowane!       " -ForegroundColor Green
Write-Host "  Otworz w przegladarce: http://localhost:8080            " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
