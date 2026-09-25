import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException

from data.models import AgentQuery
from data.sql_functions import db_path, init_db, db_get_all_products
from agent.h1_agent import run_h1_agent
from network.server import mcp
from network.client import request_producer_proposal, accept_producer_proposal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("H1_MAIN")

# !!! nie wywoływać tutaj run_h1_agent bo pojawia się błąd z `thought_signature`
async def initial_audit():
    """Wstępny audyt magazynu w czystym Pythonie po starcie systemu."""
    await asyncio.sleep(5)
    logger.info("[INITIAL AUDIT] Uruchamianie audytu magazynu H1...")
    try:
        products = db_get_all_products()
        low_stock = [p for p in products if float(p["quantity"]) < float(p.get("min_threshold", 20.0))]
        
        if not low_stock:
            logger.info("[INITIAL AUDIT] Brak produktów poniżej progu min_threshold.")
            return

        for prod in low_stock:
            item_name = prod["name"]
            item_unit = prod["unit"]
            threshold = float(prod.get("min_threshold", 20.0))
            current_qty = float(prod["quantity"])
            needed_qty = threshold - current_qty
            if needed_qty <= 0:
                needed_qty = 20.0

            logger.info(f"[INITIAL AUDIT] Wykryto brak {item_name} ({current_qty}{item_name} / min. {threshold}{item_unit}). Zamawianie {needed_qty}{item_unit} u Producenta P1...")
            
            prop = await request_producer_proposal(buyer_id="H1", item_name=item_name, quantity=needed_qty)
            if prop.get("message_type") == "PROPOSAL":
                item_data = prop.get("item", {})
                price = float(item_data.get("price", 0.0))
                total_cost = float(prop.get("total_cost", price * needed_qty))
                
                res = await accept_producer_proposal(
                    buyer_id="H1", 
                    item_name=item_name, 
                    quantity=needed_qty, 
                    price=price, 
                    total_cost=total_cost
                )
                logger.info(f"[INITIAL AUDIT] Wynik dla {item_name}: {res.get('status', 'ACCEPTED')}")
            else:
                reason = prop.get("reason", "Producent odrzucił zapytanie ofertowe.")
                logger.warning(f"[INITIAL AUDIT] Odmowa dla {item_name}: {reason}")

    except Exception as e:
        logger.error(f"[INITIAL AUDIT BŁĄD] {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(initial_audit())
    yield


app = FastAPI(title="Warehouse 1 (H1) Agent API", lifespan=lifespan)


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

    return text.replace("**", "").replace("`", "").strip()


@app.post("/chat")
async def chat_endpoint(req: AgentQuery):
    try:
        raw_response = await run_h1_agent(req.prompt, req.thread_id)
        clean_response = extract_clean_text(raw_response)
        return {"status": "success", "response": clean_response}
    except Exception as e:
        logger.error(f"[CHAT ERROR] Błąd agenta H1: {e}")
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/mcp", mcp.sse_app())

products_info = [
    {"name": "flour", "quantity": 100, "unit": "kg", "price": 3.50, "min_threshold": 50.0},
    {"name": "passata", "quantity": 200, "unit": "kg", "price": 5.80, "min_threshold": 60.0},
    {"name": "mozzarella", "quantity": 100, "unit": "kg", "price": 15.20, "min_threshold": 30.0},
    {"name": "parmigiano reggiano", "quantity": 100, "unit": "kg", "price": 28.00, "min_threshold": 15.0},
    {"name": "burrata", "quantity": 20, "unit": "kg", "price": 35.00, "min_threshold": 10.0},
    {"name": "buffala", "quantity": 30, "unit": "kg", "price": 24.00, "min_threshold": 10.0},
    {"name": "prosciutto cotto", "quantity": 80, "unit": "kg", "price": 18.99, "min_threshold": 20.0},
    {"name": "prosciutto crudo", "quantity": 80, "unit": "kg", "price": 25.00, "min_threshold": 20.0},
    {"name": "arugula", "quantity": 150, "unit": "kg", "price": 11.00, "min_threshold": 25.0},
    {"name": "lamb's lettuce", "quantity": 0, "unit": "kg", "price": 13.00, "min_threshold": 15.0},
    {"name": "salami", "quantity": 0, "unit": "kg", "price": 22.00, "min_threshold": 15.0},
]

# !! jako url do połączenia z serwerem użyć http://127.0.0.1:8004/mcp/sse
# Użyć http://127.0.0.1:8004/docs żeby przetestować interfejs API agenta H1 (Hurtowni 1) w przeglądarce.

if __name__ == "__main__":
    import uvicorn
    if not db_path.exists():
        init_db(products_info)

    uvicorn.run("main:app", host="127.0.0.1", port=8004, reload=True)