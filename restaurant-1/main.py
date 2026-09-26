"""
FastAPI REST API & MCP Server for Restaurant 1 (R1).
Unified application serving both:
1. REST API for human operator, orchestrator, and Swagger UI:
   - POST /chat      : Orchestrator / User natural language command interface
   - GET  /status    : High-level status (inventory alerts, wallet balance, health)
   - GET  /inventory : Full pantry stock and safety threshold breakdown
   - GET  /wallet    : Financial balance and transaction ledger
   - POST /cook      : Direct kitchen order execution with auto-reorder support
   - POST /audit     : Autonomous stock audit & procurement trigger
   - GET  /health    : Liveness probe
   - GET  /docs      : Interactive OpenAPI / Swagger UI
2. MCP Server (SSE) for B2B supply chain trading:
   - GET  /sse       : Server-Sent Events endpoint for wholesalers
   - POST /messages  : MCP protocol message exchange (e.g. receive_delivery)
"""

import logging
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Setup paths
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import config
from agent.agent import RestaurantBrain
from agent.tools import default_agent
from data.database import init_db
from network.server import mcp_server

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("R1_API")

# Lazy-loaded Brain instance
_brain: Optional[RestaurantBrain] = None


def get_brain() -> RestaurantBrain:
    global _brain
    if _brain is None:
        _brain = RestaurantBrain(agent_backend=default_agent)
    return _brain


# FastAPI Application
app = FastAPI(
    title="Restaurant 1 (R1) Agent API & MCP Node",
    description=(
        "Natywne REST API oraz węzeł MCP dla Restauracji nr 1 w multi-agentowym łańcuchu dostaw. "
        "Umożliwia sterowanie agentem przez zewnętrzny Orkiestrator (POST /chat), "
        "monitoring zapasów i portfela oraz automatyczny odbiór dostaw od hurtowni (MCP SSE na /sse)."
    ),
    version="2.0.0",
)

# CORS middleware for orchestrator / web UIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request / Response Models
class ChatRequest(BaseModel):
    prompt: Optional[str] = Field(
        default=None,
        description="Treść polecenia lub zapytania do agenta R1 (standard H1 / R1)",
        examples=["Przygotuj 2x margherita_classica", "Sprawdź stan magazynu i gotówki"],
    )
    polecenie: Optional[str] = Field(
        default=None,
        description="Alternatywna nazwa pola polecenia (standard R2 / Orkiestrator)",
        examples=["Zrób audyt spiżarni i domów brakujące składniki"],
    )
    thread_id: str = Field(
        default="r1_orchestrator_session",
        description="Identyfikator wątku/sesji konwersacji",
    )


class ChatResponse(BaseModel):
    status: str = Field(default="success")
    agent_id: str = Field(default="R1")
    agent_name: str = Field(default=config.AGENT_NAME)
    response: str = Field(..., description="Odpowiedź Agenta R1 (format H1/R1)")
    odpowiedz: str = Field(..., description="Kopia odpowiedzi Agenta R1 (format R2)")
    thread_id: str


class CookRequest(BaseModel):
    dish_name: str = Field(..., description="Nazwa potrawy z menu", examples=["margherita_classica"])
    quantity: int = Field(default=1, ge=1, description="Liczba porcji do przygotowania")
    auto_reorder: Optional[bool] = Field(
        default=True,
        description="Czy automatycznie złożyć zamówienie w hurtowniach przy naruszeniu progu bezpieczeństwa",
    )


# -----------------------------------------------------------------------------
# REST API Endpoints for Orchestrator & Human Operator
# -----------------------------------------------------------------------------

from fastapi.responses import HTMLResponse


@app.get("/", tags=["UI Dashboard"], response_class=HTMLResponse)
async def serve_dashboard():
    """Zwraca wizualny panel sterowania dla restauracji."""
    html_path = CURRENT_DIR / "templates" / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h3>Brak pliku szablonu w katalogu templates/index.html</h3>"


@app.get("/health", tags=["Monitoring"])
async def health():
    """Liveness probe dla Orkiestratora."""
    return {"status": "ok", "agent_id": config.AGENT_ID}


@app.post("/chat", response_model=ChatResponse, tags=["Orchestrator"])
async def chat_endpoint(req: ChatRequest):
    """
    Główny interfejs sterujący Agenta R1 dla wspólnego Orkiestratora i człowieka.
    Akceptuje polecenia w języku naturalnym (zarówno w polu 'prompt' jak i 'polecenie').
    """
    query = (req.prompt or req.polecenie or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Brak treści polecenia (wypełnij 'prompt' lub 'polecenie').")

    logger.info(f"[{config.AGENT_ID}] Otrzymano polecenie od Orkiestratora: '{query}'")

    brain = get_brain()
    try:
        if config.is_gemini_configured() and brain.client is not None:
            reply = brain.ask(query)
        else:
            # Fallback when no Gemini API key configured: handle standard operational queries
            lower_q = query.lower()
            if any(w in lower_q for w in ("inwentaryz", "stan", "magazyn", "spiżarn")):
                inv = default_agent.check_inventory()
                reply = f"Raport spiżarni R1: {inv['total_items']} pozycji. Braki/krytyczne: {inv['low_stock_items']}. Saldo: {inv['wallet_balance']:.2f} PLN."
            elif any(w in lower_q for w in ("portfel", "konto", "finans", "saldo", "pieni")):
                fin = default_agent.get_financial_status()
                reply = f"Portfel R1: Saldo {fin['balance']:.2f} {fin['currency']}."
            elif "audyt" in lower_q:
                inv = default_agent.check_inventory()
                reply = f"Autonomiczny audyt R1: Wykryto {len(inv['low_stock_items'])} pozycji na progu bezpieczeństwa: {inv['low_stock_items']}."
            else:
                reply = f"Agent R1 przyjął polecenie: '{query}'. Portfel i magazyn sprawne."

        logger.info(f"[{config.AGENT_ID}] Odpowiedź wygenerowana pomyślnie.")
        return ChatResponse(
            status="success",
            agent_id=config.AGENT_ID,
            agent_name=config.AGENT_NAME,
            response=reply,
            odpowiedz=reply,
            thread_id=req.thread_id,
        )
    except Exception as e:
        logger.error(f"[{config.AGENT_ID}] Błąd podczas przetwarzania zapytania: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status", tags=["Orchestrator"])
async def status_endpoint():
    """
    Zwraca ustrukturyzowany, pełny stan restauracji (magazyn, portfel, alerty) w formacie JSON
    bez konieczności odpytywania modelu LLM.
    """
    inv = default_agent.check_inventory()
    fin = default_agent.get_financial_status()
    return {
        "status": "ONLINE",
        "agent_id": config.AGENT_ID,
        "name": config.AGENT_NAME,
        "wallet": {
            "balance": fin.get("balance", 0.0),
            "currency": fin.get("currency", "PLN"),
            "account_id": fin.get("account_id", "R1_WALLET"),
        },
        "inventory_summary": {
            "total_items": inv.get("total_items", 0),
            "low_stock_items": inv.get("low_stock_items", []),
            "has_shortages": len(inv.get("low_stock_items", [])) > 0,
        },
        "mcp_server": {
            "transport": "sse",
            "url": f"http://127.0.0.1:{config.PORT}/sse",
            "capabilities": ["receive_delivery", "get_node_info"],
        },
    }


@app.get("/inventory", tags=["Pantry & Kitchen"])
async def get_inventory_endpoint():
    """Zwraca szczegółowy stan 11 surowców w spiżarni wraz z progami bezpieczeństwa."""
    return default_agent.check_inventory()


@app.get("/wallet", tags=["Finance"])
async def get_wallet_endpoint():
    """Zwraca saldo portfela finansowego R1 oraz historię ostatnich transakcji."""
    return default_agent.get_financial_status()


@app.post("/cook", tags=["Pantry & Kitchen"])
async def cook_dish_endpoint(req: CookRequest):
    """
    Wykonuje zamówienie kuchenne: odlicza surowce z bazy SQL.
    Jeśli stan surowca spadnie na lub poniżej progu bezpieczeństwa,
    automatycznie uruchamia proces przetargowy CNP do hurtowni (H1/H2).
    """
    res = default_agent.consume_ingredients(
        dish_name=req.dish_name,
        quantity=req.quantity,
        auto_reorder=req.auto_reorder,
    )
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.post("/audit", tags=["Pantry & Kitchen"])
async def audit_endpoint():
    """Wymusza natychmiastowy audyt spiżarni i automatyczne uzupełnienie braków."""
    brain = get_brain()
    if config.is_gemini_configured() and brain.client is not None:
        rep = brain.run_autonomous_audit()
        return {"status": "success", "audit_report": rep}
    else:
        inv = default_agent.check_inventory()
        return {"status": "success", "audit_report": f"Sprawdzono magazyn R1: {inv['low_stock_items']}"}


# -----------------------------------------------------------------------------
# Mount MCP SSE Application directly onto FastAPI root
# Enables /sse and /messages on the same port (8002) for B2B Wholesalers
# -----------------------------------------------------------------------------
app.mount("", mcp_server.sse_app())


def main():
    """Uruchamia zintegrowany serwer FastAPI + MCP na porcie R1 (8002)."""
    # Upewniamy się, że baza SQLite jest zainicjalizowana
    init_db(config.DB_PATH, initial_balance=config.INITIAL_BALANCE, currency=config.DEFAULT_CURRENCY)
    logger.info(
        f"[{config.AGENT_ID}] Uruchamianie zintegrowanego serwera FastAPI + MCP na http://127.0.0.1:{config.PORT} "
        f"(REST API: /docs, /chat | MCP: /sse)"
    )
    uvicorn.run(app, host="127.0.0.1", port=config.PORT, log_level="info")

if __name__ == "__main__":
    main()
