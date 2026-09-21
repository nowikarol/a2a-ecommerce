import logging
from fastapi import FastAPI, HTTPException
from data.models import AgentQuery
from data.sql_functions import db_path, init_db
from agent.h1_agent import run_h1_agent
from network.server import mcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("H1_MAIN")

app = FastAPI(title="Warehouse 1 (H1) Agent API")

@app.post("/chat")
async def chat_endpoint(req: AgentQuery):
    """Interfejs użytkownika do sterowania Agentem Hurtowni (np. 'Kup 50kg mąki')"""
    try:
        odpowiedz = run_h1_agent(req.prompt, req.thread_id)
        return {"status": "success", "response": odpowiedz}
    except Exception as e:
        logger.error(f"Błąd agenta H1: {e}")
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/mcp", mcp.sse_app())

products_info = [
    {"name": "flour", "quantity": 100, "unit": "kg", "price": 3.50},
    {"name": "passata", "quantity": 300, "unit": "kg", "price": 5.80},
    {"name": "mozzarella", "quantity": 200, "unit": "kg", "price": 8.50},
    {"name": "parmigiano reggiano", "quantity": 100, "unit": "kg", "price": 18.00},
    {"name": "burrata", "quantity": 20, "unit": "kg", "price": 12.00},
    {"name": "buffala", "quantity": 30, "unit": "kg", "price": 11.00},
    {"name": "prosciutto cotto", "quantity": 80, "unit": "kg", "price": 14.50},
    {"name": "prosciutto crudo", "quantity": 80, "unit": "kg", "price": 16.99},
    {"name": "arugula", "quantity": 150, "unit": "kg", "price": 4.00},
    {"name": "lamb's lettuce", "quantity": 0, "unit": "kg", "price": 4.99},
    {"name": "salami", "quantity": 0, "unit": "kg", "price": 9.00},
]

# !! jako url do połączenia z serwerem użyć http://127.0.0.1:8004/mcp/sse
# Użyć http://127.0.0.1:8004/docs żeby przetestować interfejs API agenta H1 (Hurtowni 1) w przeglądarce.

if __name__ == "__main__":
    import uvicorn
    if not db_path.exists():
        init_db(products_info)

    uvicorn.run("main:app", host="127.0.0.1", port=8004, reload=True)