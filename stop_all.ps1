# =============================================================================
# A2A Supply Chain - Skrypt zatrzymujący (stop_all.ps1)
# Zatrzymuje procesy nasłuchujące na portach ekosystemu A2A
# =============================================================================

$ports = @(8001, 8002, 8003, 8004, 8005, 8022, 8080)
$stopped = 0

Write-Host "Zatrzymywanie serwerow ekosystemu A2A..." -ForegroundColor Cyan

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($p in $pids) {
            try {
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
                Write-Host "Zatrzymano proces PID $p na porcie $port" -ForegroundColor Green
                $stopped++
            } catch {
                Write-Host "Blad podczas zatrzymywania PID $p na porcie $port" -ForegroundColor Red
            }
        }
    }
}

if ($stopped -eq 0) {
    Write-Host "Zaden proces nie nasluchiwal na portach ekosystemu." -ForegroundColor Yellow
} else {
    Write-Host "Zakonczono. Zatrzymano procesy powiazane z portami." -ForegroundColor Green
}
