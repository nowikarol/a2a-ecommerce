import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException

from data.models import AgentQuery
from data.sql_functions import db_path, init_db
from agent.h1_agent import run_h1_agent
from network.server import mcp, trigger_auto_procurement
import data.sql_functions as sql_funcs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("H1_MAIN")

async def periodic_audit():
    """Cykliczny audyt magazynu w tle uruchamiany co 3 minuty."""
    await asyncio.sleep(10)
    
    while True:
        logger.info("[BACKGROUND AUDIT] Rozpoczynam cykliczny przegląd stanu magazynu...")
        try:
            all_products = sql_funcs.db_get_all_products()
            for p in all_products:
                current = float(p["quantity"])
                threshold = float(p.get("min_threshold", 20.0))
                
                if current < threshold:
                    logger.info(f"[BACKGROUND AUDIT] Wykryto brak: '{p['name']}' (Stan: {current}, Próg: {threshold}). Uzupełniam...")
                    await trigger_auto_procurement(p["name"])
                    
        except Exception as e:
            logger.error(f"[BACKGROUND AUDIT ERROR] Błąd podczas cyklicznego audytu: {e}")
            
        # 3 minuty do kolejnego sprawdzenia
        await asyncio.sleep(180)


@asynccontextmanager
async def lifespan(app: FastAPI):
    audit_task = asyncio.create_task(periodic_audit())
    yield
    audit_task.cancel()


app = FastAPI(title="Warehouse 1 (H1) Agent API", lifespan=lifespan)

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
app.mount("/mcp", mcp.sse_app())

if __name__ == "__main__":
    import uvicorn
    if not db_path.exists():
        init_db(products_info)

    uvicorn.run("main:app", host="127.0.0.1", port=8004, reload=True)