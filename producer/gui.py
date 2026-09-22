import asyncio
import datetime
import json
import sqlite3
from flask import Flask, jsonify, render_template_string, request
from fastmcp import Client

import setup_db  # Importujemy moduł resetujący bazę

app = Flask(__name__)
app.json.sort_keys = False
DB_PATH = "producer.db"
MCP_SERVER_URL = "http://127.0.0.1:8001/sse"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# API dla Dashboardu
# ---------------------------------------------------------------------------


@app.route("/api/db", methods=["GET"])
def get_db_state():
    """Zwraca aktualny stan wszystkich tabel w bazie SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products")
    products = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM production_plan")
    production_plan = [dict(row) for row in cursor.fetchall()]

    cursor.execute(
        "SELECT * FROM sales_transactions ORDER BY transaction_date DESC"
    )
    sales = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify(
        {
            "products": products,
            "production_plan": production_plan,
            "sales_transactions": sales,
        }
    )


@app.route("/api/send_request", methods=["POST"])
def send_mcp_request():
    """Wysyła zapytanie do serwera MCP na podstawie przekazanego JSONa."""
    data = request.json or {}
    tool_name = data.get("tool")
    payload = data.get("payload", {})

    if not tool_name or not isinstance(payload, dict):
        return (
            jsonify({"error": "Nieprawidłowy format żądania (wymagane: tool, payload)"}),
            400,
        )

    async def _call():
        async with Client(MCP_SERVER_URL) as client:
            return await client.call_tool(tool_name, arguments=payload)

    try:
        result = asyncio.run(_call())

        # Konwersja wyniku MCP do słownika / JSONa
        if hasattr(result, "content"):
            content_data = []
            for item in result.content:
                if hasattr(item, "text"):
                    try:
                        content_data.append(json.loads(item.text))
                    except Exception:
                        content_data.append(item.text)
                else:
                    content_data.append(str(item))
            response_payload = (
                content_data[0] if len(content_data) == 1 else content_data
            )
        elif hasattr(result, "data"):
            response_payload = result.data
        else:
            response_payload = str(result)

        return jsonify(
            {
                "status": "success",
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "response": response_payload,
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                    "error": str(e),
                }
            ),
            500,
        )


@app.route("/api/reset_db", methods=["POST"])
def reset_database():
    """Resetuje bazę danych używając funkcji z setup_db.py."""
    try:
        conn = sqlite3.connect(DB_PATH)
        setup_db.create_tables(conn)
        setup_db.insert_sample_data(conn)
        conn.close()
        return jsonify(
            {
                "message": "Baza danych została pomyślnie zresetowana!",
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            }
        )
    except Exception as e:
        return jsonify({"error": f"Błąd resetu bazy: {str(e)}"}), 500


@app.route("/api/sql", methods=["POST"])
def run_custom_sql():
    """Uruchamia dowolne zapytanie SQL w celach debugowania."""
    query = request.json.get("query", "").strip()
    if not query:
        return jsonify({"error": "Puste zapytanie SQL"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query)
        if query.upper().startswith("SELECT"):
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return jsonify({"type": "select", "result": rows})
        else:
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return jsonify(
                {"type": "execute", "result": f"Wykonano. Zmienionych wierszy: {affected}"}
            )
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Interfejs Graficzny (HTML / CSS / JS)
# ---------------------------------------------------------------------------


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <title>Producer P1 - MCP Debugger & Database Monitor</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background-color: #1e1e1e; border: 1px solid #333; color: #e0e0e0; margin-bottom: 20px; }
        .card-header { background-color: #252526; border-bottom: 1px solid #333; font-weight: bold; }
        .table-dark { background-color: #1e1e1e; color: #d4d4d4; }
        .table-dark th { background-color: #2a2a2a; border-color: #444; }
        .table-dark td { border-color: #333; font-size: 0.9rem; }
        textarea, input, select { background-color: #252526 !important; color: #00ff66 !important; border: 1px solid #444 !important; font-family: monospace; }
        textarea:focus, input:focus, select:focus { box-shadow: 0 0 5px #0d6efd !important; }
        pre { background-color: #111; color: #00ff66; padding: 12px; border-radius: 6px; border: 1px solid #333; max-height: 250px; overflow-y: auto; font-size: 0.85rem; }
        .badge-live { animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
        .btn-custom { font-weight: 600; }
        .nav-tabs .nav-link { color: #aaa; border: none; }
        .nav-tabs .nav-link.active { background-color: #1e1e1e; color: #0d6efd; border-bottom: 2px solid #0d6efd; font-weight: bold; }
    </style>
</head>
<body class="p-3">
    <div class="container-fluid">
        <!-- Nagłówek -->
        <div class="d-flex justify-content-between align-items-center mb-3 pb-2 border-bottom border-secondary">
            <h3 class="m-0 text-primary"><i class="bi bi-cpu"></i> Producer P1 — MCP Dashboard & DB Monitor</h3>
            <div>
                <span class="badge bg-success badge-live me-2">● Podgląd na żywo (1.5s)</span>
                <button class="btn btn-outline-warning btn-sm" onclick="resetDatabase()"><i class="bi bi-arrow-counterclockwise"></i> Reset Bazy Danych</button>
            </div>
        </div>

        <div class="row">
            <!-- LEWA STRONA: PODGLĄD BAZY DANYCH (LIVE) -->
            <div class="col-lg-7">
                <div class="card shadow">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span><i class="bi bi-database me-2"></i>Stan Bazy Danych (`producer.db`)</span>
                        <small id="lastDbUpdate" class="text-muted">Aktualizacja...</small>
                    </div>
                    <div class="card-body p-2">
                        <ul class="nav nav-tabs mb-2" id="dbTabs" role="tablist">
                            <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-products">Produkty (<span id="cnt-products">0</span>)</button></li>
                            <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-plan">Plan Produkcji (<span id="cnt-plan">0</span>)</button></li>
                            <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-sales">Transakcje Sprzedaży (<span id="cnt-sales">0</span>)</button></li>
                        </ul>
                        <div class="tab-content">
                            <!-- Produkty -->
                            <div class="tab-pane fade show active" id="tab-products">
                                <div class="table-responsive" style="max-height: 480px;">
                                    <table class="table table-dark table-hover table-striped mb-0">
                                        <thead><tr><th>Kod</th><th>Nazwa</th><th>Cena [zł]</th><th>Stan mag.</th><th>Jedn.</th></tr></thead>
                                        <tbody id="tbl-products"></tbody>
                                    </table>
                                </div>
                            </div>
                            <!-- Plan produkcji -->
                            <div class="tab-pane fade" id="tab-plan">
                                <div class="table-responsive" style="max-height: 480px;">
                                    <table class="table table-dark table-hover table-striped mb-0">
                                        <thead><tr><th>ID</th><th>Kod produktu</th><th>Data produkcji</th><th>Ilość</th><th>Status</th></tr></thead>
                                        <tbody id="tbl-plan"></tbody>
                                    </table>
                                </div>
                            </div>
                            <!-- Transakcje sprzedaży -->
                            <div class="tab-pane fade" id="tab-sales">
                                <div class="table-responsive" style="max-height: 480px;">
                                    <table class="table table-dark table-hover table-striped mb-0">
                                        <thead><tr><th>ID</th><th>Kod</th><th>Ilość</th><th>Cena jedn.</th><th>Suma</th><th>Kupujący</th><th>Data</th></tr></thead>
                                        <tbody id="tbl-sales"></tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Konsola SQL Debugera -->
                <div class="card shadow">
                    <div class="card-header"><i class="bi bi-terminal me-2"></i>Konsola SQL (Debuger Bazy)</div>
                    <div class="card-body">
                        <div class="input-group mb-2">
                            <input type="text" id="sqlQuery" class="form-control" placeholder="np. SELECT * FROM products WHERE stock_quantity < 100">
                            <button class="btn btn-outline-info" onclick="runSql()">Wykonaj SQL</button>
                        </div>
                        <pre id="sqlResult" class="mb-0" style="display:none; max-height:120px;"></pre>
                    </div>
                </div>
            </div>

            <!-- PRAWA STRONA: TESTER ZAPYTANIA JSON & MCP -->
            <div class="col-lg-5">
                <div class="card shadow">
                    <div class="card-header"><i class="bi bi-send me-2"></i>Wysyłanie Ładunku JSON do MCP</div>
                    <div class="card-body">
                        <div class="mb-2">
                            <label class="form-label mb-1">Szybki szablon (Preset):</label>
                            <select id="presetSelect" class="form-select form-select-sm" onchange="loadPreset()">
                                <option value="check_availability">1. check_availability (Sprawdź dostępność)</option>
                                <option value="request_offer">2. request_offer (Poproś o ofertę)</option>
                                <option value="accept_offer">3. accept_offer (Akceptuj ofertę i kup)</option>
                            </select>
                        </div>

                        <div class="mb-2">
                            <label class="form-label mb-1">Wybrane Narzędzie MCP:</label>
                            <select id="toolSelect" class="form-select form-select-sm">
                                <option value="check_availability">check_availability</option>
                                <option value="request_offer">request_offer</option>
                                <option value="accept_offer">accept_offer</option>
                            </select>
                        </div>

                        <div class="mb-2">
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <label class="form-label m-0">Payload (JSON):</label>
                                <button class="btn btn-sm btn-link text-decoration-none p-0 text-info" onclick="prettifyJson()"><i class="bi bi-magic"></i> Formatuj JSON</button>
                            </div>
                            <textarea id="jsonInput" class="form-control" rows="8"></textarea>
                        </div>

                        <button class="btn btn-primary w-100 btn-custom" onclick="sendMcpRequest()"><i class="bi bi-play-fill me-1"></i> Wyślij zapytanie do serwera MCP</button>
                    </div>
                </div>

                <!-- Wynik Odpowiedzi -->
                <div class="card shadow">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <span><i class="bi bi-code-square me-2"></i>Odpowiedź Serwera MCP</span>
                        <span id="responseStatus" class="badge bg-secondary">Brak wysyłki</span>
                    </div>
                    <div class="card-body p-2">
                        <pre id="responseLog" class="m-0">// Wynik odpowiedzi JSON pojawi się tutaj...</pre>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const PRESETS = {
            check_availability: {
                tool: "check_availability",
                payload: {
                    sender_id: "H1",
                    receiver_id: "P1",
                    item_name: "flour",
                    quantity: 50.0
                }
            },
            request_offer: {
                tool: "request_offer",
                payload: {
                    sender_id: "H1",
                    receiver_id: "P1",
                    item_name: "flour",
                    quantity: 50.0
                }
            },
            accept_offer: {
                tool: "accept_offer",
                payload: {
                    sender_id: "H1",
                    receiver_id: "P1",
                    item_name: "flour",
                    quantity: 50.0,
                    price: 2.25,
                    total_cost: 112.50
                }
            }
        };

        function loadPreset() {
            const key = document.getElementById('presetSelect').value;
            const preset = PRESETS[key];
            document.getElementById('toolSelect').value = preset.tool;
            document.getElementById('jsonInput').value = JSON.stringify(preset.payload, null, 2);
        }

        function prettifyJson() {
            try {
                const val = document.getElementById('jsonInput').value;
                const parsed = JSON.parse(val);
                document.getElementById('jsonInput').value = JSON.stringify(parsed, null, 2);
            } catch(e) {
                alert("Niepoprawny format JSON! " + e.message);
            }
        }

        async function fetchDbData() {
            try {
                const res = await fetch('/api/db');
                const data = await res.json();

                // 1. Tabela Produkty
                document.getElementById('cnt-products').innerText = data.products.length;
                let htmlProducts = '';
                data.products.forEach(p => {
                    htmlProducts += `<tr>
                        <td><code>${p.product_code}</code></td>
                        <td>${p.name}</td>
                        <td>${p.unit_price.toFixed(2)}</td>
                        <td class="${p.stock_quantity < 20 ? 'text-danger fw-bold' : 'text-success'}">${p.stock_quantity}</td>
                        <td>${p.unit}</td>
                    </tr>`;
                });
                document.getElementById('tbl-products').innerHTML = htmlProducts;

                // 2. Tabela Plan Produkcji
                document.getElementById('cnt-plan').innerText = data.production_plan.length;
                let htmlPlan = '';
                data.production_plan.forEach(plan => {
                    htmlPlan += `<tr>
                        <td>${plan.id}</td>
                        <td><code>${plan.product_code}</code></td>
                        <td>${plan.production_date}</td>
                        <td>${plan.quantity}</td>
                        <td><span class="badge bg-info">${plan.status}</span></td>
                    </tr>`;
                });
                document.getElementById('tbl-plan').innerHTML = htmlPlan;

                // 3. Tabela Transakcje
                document.getElementById('cnt-sales').innerText = data.sales_transactions.length;
                let htmlSales = '';
                data.sales_transactions.forEach(s => {
                    htmlSales += `<tr>
                        <td>${s.id}</td>
                        <td><code>${s.product_code}</code></td>
                        <td>${s.quantity}</td>
                        <td>${s.unit_price.toFixed(2)}</td>
                        <td><strong>${s.total_cost.toFixed(2)} zł</strong></td>
                        <td><span class="badge bg-warning text-dark">${s.buyer_id}</span></td>
                        <td><small class="text-muted">${s.transaction_date.replace('T', ' ').substring(0, 19)}</small></td>
                    </tr>`;
                });
                document.getElementById('tbl-sales').innerHTML = htmlSales || '<tr><td colspan="7" class="text-center text-muted">Brak zapisanych transakcji</td></tr>';

                document.getElementById('lastDbUpdate').innerText = 'Ostatnio: ' + new Date().toLocaleTimeString();
            } catch(e) {
                console.error("Błąd pobierania danych bazy:", e);
            }
        }

        async function sendMcpRequest() {
            const tool = document.getElementById('toolSelect').value;
            let payloadText = document.getElementById('jsonInput').value;
            let payloadJson;

            try {
                payloadJson = JSON.parse(payloadText);
            } catch(e) {
                alert("Błąd w kodzie JSON payloadu: " + e.message);
                return;
            }

            const statusBadge = document.getElementById('responseStatus');
            statusBadge.className = "badge bg-warning text-dark";
            statusBadge.innerText = "Wysyłanie...";

            try {
                const res = await fetch('/api/send_request', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ tool: tool, payload: payloadJson })
                });

                const data = await res.json();
                document.getElementById('responseLog').innerText = JSON.stringify(data, null, 2);

                if (res.ok) {
                    statusBadge.className = "badge bg-success";
                    statusBadge.innerText = "Sukces 200 OK (" + data.timestamp + ")";
                    fetchDbData(); // Natychmiastowe odświeżenie bazy po udanym zapytaniu
                } else {
                    statusBadge.className = "badge bg-danger";
                    statusBadge.innerText = "Błąd (" + data.timestamp + ")";
                }
            } catch(e) {
                statusBadge.className = "badge bg-danger";
                statusBadge.innerText = "Błąd połączenia";
                document.getElementById('responseLog').innerText = "// Błąd połączenia z GUI backendem: " + e.message;
            }
        }

        async function resetDatabase() {
            if (!confirm("Czy na pewno chcesz zresetować bazę danych do stanu początkowego?")) return;
            try {
                const res = await fetch('/api/reset_db', { method: 'POST' });
                const data = await res.json();
                alert(data.message || data.error);
                fetchDbData();
            } catch(e) {
                alert("Błąd resetowania bazy: " + e.message);
            }
        }

        async function runSql() {
            const query = document.getElementById('sqlQuery').value;
            if (!query) return;

            try {
                const res = await fetch('/api/sql', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ query: query })
                });
                const data = await res.json();
                const resBox = document.getElementById('sqlResult');
                resBox.style.display = 'block';
                resBox.innerText = JSON.stringify(data, null, 2);
                fetchDbData();
            } catch(e) {
                alert("Błąd SQL: " + e.message);
            }
        }

        // Inicjalizacja
        loadPreset();
        fetchDbData();
        setInterval(fetchDbData, 1500); // Polling bazy co 1.5 sekundy
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Uruchamianie GUI Dashboardu pod adresem: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=True)