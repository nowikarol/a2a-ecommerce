# main.py
import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
import json

from data.models import TradeMessage
import data.sql_functions as sql_ops
from handlers.mcp_tools import register_mcp_tools

# =====================================================================
# Konfiguracja i baza danych
# =====================================================================

producer_url = "http://127.0.0.1:8000/a2a/message" 
AGENT_ID = "H1"

app = FastAPI(title="Hurtownia 1")

mcp = FastMCP("warehouse-1")

mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)

# === Narzędzia MCP ===
register_mcp_tools(mcp, AGENT_ID)

# Początkowe produkty
products_info = [
    {"name": "flour", "quantity": 100, "price": 3.50},
    {"name": "passata", "quantity": 300, "price": 5.80},
    {"name": "mozzarella", "quantity": 200, "price": 8.50},
    {"name": "parmigiano reggiano", "quantity": 100, "price": 18.00},
    {"name": "burrata", "quantity": 20, "price": 12.00},
    {"name": "buffala", "quantity": 30, "price": 11.00},
    {"name": "prosciutto cotto", "quantity": 80, "price": 14.50},
    {"name": "prosciutto crudo", "quantity": 80, "price": 16.99},
    {"name": "arugula", "quantity": 150, "price": 4.00},
    {"name": "lamb's lettuce", "quantity": 0, "price": 4.99},
    {"name": "salami", "quantity": 0, "price": 9.00},
]

if not sql_ops.path.exists():
    sql_ops.init_db(products_info)


# =====================================================================
# Endpointy REST
# =====================================================================

@app.get("/products")
def get_products():
    """Zwraca aktualne informacje o produktach."""
    conn = sql_ops.get_connection()
    try:
        cursor = conn.execute("SELECT name, quantity, price FROM products")
        rows = cursor.fetchall()
        return [{"name": r[0], "quantity": r[1], "price": r[2]} for r in rows]
    finally:
        conn.close()


@app.post("/a2a/message")
async def handle_message(msg: TradeMessage):
    """Obsługuje wiadomości (CALL_FOR_PROPOSAL, ACCEPT_PROPOSAL, REJECT_PROPOSAL)."""

    if msg.message_type == "CALL_FOR_PROPOSAL":
        mcp_result = await mcp.call_tool(
            "get_price_proposal",
            arguments={
                "sender_id": msg.sender_id,
                "item_name": msg.item.name,
                "quantity": msg.item.quantity,
            },
        )
        return json.loads(mcp_result[0].text)

    elif msg.message_type == "ACCEPT_PROPOSAL":
        mcp_result = await mcp.call_tool(
            "finalize_order",
            arguments={
                "sender_id": msg.sender_id,
                "item_name": msg.item.name,
                "quantity": msg.item.quantity,
                "total_cost": msg.total_cost,
            },
        )
        return json.loads(mcp_result[0].text)

    elif msg.message_type == "REJECT_PROPOSAL":
        return {"status": "REJECTED", "message": "Offer was rejected."}

    return {"status": "UNKNOWN_MESSAGE_TYPE", "message_type": msg.message_type}

# Zakup od Producenta

@app.post("/a2a/buy/request-offer")
def rest_request_producer_offer(item_name: str, quantity: int):
    """Wysyła CALL_FOR_PROPOSAL do Producenta i zwraca wycenę (PROPOSAL)."""
    from handlers.internal_ops import request_offer
    return request_offer(AGENT_ID, producer_url, item_name, quantity)

@app.post("/a2a/buy/accept-offer")
def rest_accept_producer_offer(item_name: str, quantity: int, price: float):
    """Wysyła ACCEPT_PROPOSAL do Producenta i aktualizuje zapasy."""
    from handlers.internal_ops import accept_offer
    return accept_offer(AGENT_ID, producer_url, item_name, quantity, price)

if __name__ == "__main__":
    uvicorn.run(app, port=8000)  #do linku trzeba dopisać /docs!!!!