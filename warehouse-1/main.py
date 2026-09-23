import logging
import re
from fastapi import FastAPI, HTTPException
from data.models import AgentQuery
from data.sql_functions import db_path, init_db
from agent.h1_agent import run_h1_agent
from network.server import mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("H1_MAIN")

app = FastAPI(title="Warehouse 1 (H1) Agent API")


def extract_clean_text(raw_data) -> str:
    """
    Wyciąga czysty tekst wiadomości, ignorując struktury list, 
    słowników, signature oraz zbędne znaki Markdown.
    """
    text = ""

    if isinstance(raw_data, list) and len(raw_data) > 0:
        first_elem = raw_data[0]
        if isinstance(first_elem, dict):
            text = first_elem.get("text", str(first_elem))
        else:
            text = str(first_elem)
    elif isinstance(raw_data, dict):
        text = raw_data.get("text", str(raw_data))
    else:
        text = str(raw_data)

    text = text.replace("**", "").replace("`", "").strip()
    return text


@app.post("/chat")
async def chat_endpoint(req: AgentQuery):
    """Interfejs użytkownika do sterowania Agentem Hurtowni."""
    print(f"\n ZAPYTANIE: {req.prompt}")

    try:
        raw_response = await run_h1_agent(req.prompt, req.thread_id)
        clean_response = extract_clean_text(raw_response)
        print(f"ODPOWIEDŹ:\n{clean_response}\n")
        return {
            "status": "success",
            "response": clean_response
        }
    except Exception as e:
        logger.error(f"Błąd agenta H1: {e}")
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/mcp", mcp.sse_app())

products_info = [
    {"name": "flour", "quantity": 100, "unit": "kg", "price": 3.50},
    {"name": "passata", "quantity": 200, "unit": "kg", "price": 5.80},
    {"name": "mozzarella", "quantity": 100, "unit": "kg", "price": 15.00},
    {"name": "parmigiano reggiano", "quantity": 100, "unit": "kg", "price": 28.00},
    {"name": "burrata", "quantity": 20, "unit": "kg", "price": 20.00},
    {"name": "buffala", "quantity": 30, "unit": "kg", "price": 24.00},
    {"name": "prosciutto cotto", "quantity": 80, "unit": "kg", "price": 18.00},
    {"name": "prosciutto crudo", "quantity": 80, "unit": "kg", "price": 25.00},
    {"name": "arugula", "quantity": 150, "unit": "kg", "price": 11.00},
    {"name": "lamb's lettuce", "quantity": 0, "unit": "kg", "price": 13.00},
    {"name": "salami", "quantity": 0, "unit": "kg", "price": 22.00},
]

# !! jako url do połączenia z serwerem użyć http://127.0.0.1:8004/mcp/sse
# Użyć http://127.0.0.1:8004/docs żeby przetestować interfejs API agenta H1 (Hurtowni 1) w przeglądarce.

if __name__ == "__main__":
    import uvicorn
    if not db_path.exists():
        init_db(products_info)

    uvicorn.run("main:app", host="127.0.0.1", port=8004, reload=True)