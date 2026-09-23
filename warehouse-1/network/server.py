# ============================= Serwer FastMCP (Hurtownia H1) ================================
import sys
import os
import json
import logging
import asyncio
from pathlib import Path
from dotenv import load_dotenv

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from mcp import ClientSession
from mcp.client.sse import sse_client
import data.sql_functions as sql_funcs
from typing import Union, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

from data.models import TradeMessage, Item
from data.sql_functions import db_get_product, db_get_all_products, db_process_sale_transaction

AGENT_ID = "H1"

BUYER_URLS = {
    "R1": os.getenv("RESTAURANT1_URL", "http://127.0.0.1:8002/sse"),
    "R2": os.getenv("RESTAURANT2_URL", "http://127.0.0.1:8003/sse"),
}

logger = logging.getLogger("mcp_h1_server")
mcp = FastMCP("Hurtownia_H1")


async def send_delivery_to_buyer(buyer_id: str, delivery_payload: dict):
    """Łączy się z odpowiednią restauracją i wywołuje narzędzie 'receive_delivery'."""
    buyer_url = BUYER_URLS.get(buyer_id)
    if not buyer_url:
        logger.error(f"[{AGENT_ID}] BŁĄD: Brak skonfigurowanego URL dla kupującego: {buyer_id}")
        return

    try:
        # Krótki timeout połączenia, żeby nie wisieć w nieskończoność
        async with sse_client(buyer_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("receive_delivery", arguments={"delivery_data": delivery_payload})
                logger.info(f"[{AGENT_ID} -> {buyer_id}] Potwierdzenie dostawy: {result}")
    except Exception as error:
        logger.error(f"[{AGENT_ID} -> {buyer_id} BŁĄD DOSTAWY]: {error}")


@mcp.tool()
def get_inventory() -> str:
    """Zwraca pełną listę produktów dostępnych w magazynie Hurtowni H1."""
    products = db_get_all_products()
    items = [Item(name=p["name"], quantity=p["quantity"], unit=p["unit"], price=p["price"]) for p in products]
    return TradeMessage(sender_id=AGENT_ID, receiver_id="ALL", message_type="INVENTORY_LIST", items=items).model_dump_json()


@mcp.tool()
def check_availability(receiver_id: str, item: Item, sender_id: str = "R2", message_type: str = "AVAILABILITY_REQUEST") -> str:
    """Sprawdza dostępność wskazanego towaru w magazynie (Krok 1 CNP)."""
    db_row = db_get_product(item.name.strip())
    avail_qty = float(db_row["quantity"]) if db_row else 0.0
    actual_unit = db_row["unit"] if db_row else item.unit
    price = float(db_row["price"]) if db_row else (item.price or 0.0)

    return TradeMessage(
        sender_id=AGENT_ID,
        receiver_id=sender_id,
        message_type="AVAILABILITY_RESPONSE",
        item=Item(name=item.name, quantity=item.quantity, unit=actual_unit, price=price),
        is_available=avail_qty >= item.quantity,
        available_quantity=avail_qty
    ).model_dump_json()


@mcp.tool()
def request_offer(receiver_id: str, item: Item, sender_id: str = "R2", message_type: str = "CALL_FOR_PROPOSAL") -> str:
    """Przetwarza zapytanie i zwraca wycenę towaru (Krok 2 CNP - PROPOSAL)."""
    db_row = db_get_product(item.name.strip())
    
    if not db_row or float(db_row.get("quantity", 0)) < item.quantity:
        return TradeMessage(
            sender_id=AGENT_ID,
            receiver_id=sender_id,
            message_type="REJECT_PROPOSAL",
            item=Item(name=item.name, quantity=item.quantity, 
                      unit=db_row["unit"] if db_row else item.unit, 
                      price=float(db_row["price"]) if db_row else (item.price or 0.0)),
            reason="Hurtownia H1 nie posiada wystarczającej ilości towaru na stanie."
        ).model_dump_json()

    price = float(db_row["price"])
    return TradeMessage(
        sender_id=AGENT_ID,
        receiver_id=sender_id,
        message_type="PROPOSAL",
        item=Item(name=item.name, quantity=item.quantity, unit=db_row["unit"], price=price),
        total_cost=round(item.quantity * price, 2)
    ).model_dump_json()


@mcp.tool()
async def accept_offer(receiver_id: str, item: Item, total_cost: float, sender_id: str = "R2", message_type: str = "ACCEPT_PROPOSAL") -> str:
    """Obsługuje akceptację oferty przez Kupującego (Krok 4 & 5 CNP)."""
    db_row = db_get_product(item.name.strip())
    
    actual_unit = db_row["unit"] if db_row else item.unit
    actual_price = item.price if (item.price and item.price > 0) else (float(db_row["price"]) if db_row else 0.0)
    confirmed_item = Item(name=item.name, quantity=item.quantity, unit=actual_unit, price=actual_price)

    if not db_process_sale_transaction(partner=sender_id, item_name=item.name.strip(), quantity=item.quantity, total_cost=total_cost):
        return TradeMessage(
            sender_id=AGENT_ID, receiver_id=sender_id, message_type="REJECT_PROPOSAL",
            item=confirmed_item, reason="Błąd bazy danych lub brak towaru w H1."
        ).model_dump_json()

    # Powiadomienie o dostawie uruchamiamy w TLE (asyncio.create_task), żeby NIE blokować pętli SSE!
    delivery_payload = TradeMessage(
        sender_id=AGENT_ID, receiver_id=sender_id, message_type="DELIVERY",
        item=confirmed_item, total_cost=total_cost
    ).model_dump(mode="json")
    
    asyncio.create_task(send_delivery_to_buyer(buyer_id=sender_id, delivery_payload=delivery_payload))

    return TradeMessage(
        sender_id=AGENT_ID, receiver_id=sender_id, message_type="ACCEPT_PROPOSAL",
        item=confirmed_item, total_cost=total_cost
    ).model_dump_json()


@mcp.tool()
async def receive_delivery(
    sender_id: str = "P1",
    receiver_id: str = "H1",
    item: Optional[Dict[str, Any]] = None,
    item_name: Optional[str] = None,
    quantity: Optional[float] = None,
    total_cost: float = 0.0,
    message_type: str = "DELIVERY",
    status: str = "DELIVERED"
) -> str:
    """Narzędzie wywoływane przez Producenta (P1) po dostarczeniu towaru."""
    if isinstance(item, dict):
        item_name = item.get("name") or item.get("item_name") or item_name
        quantity = item.get("quantity") if item.get("quantity") is not None else quantity

    if not item_name or quantity is None:
        return json.dumps({
            "status": "FAILED",
            "reason": f"Brakujące pola towaru: item_name={item_name}, quantity={quantity}"
        })

    logger.info(f"Otrzymano dostawę od {sender_id}: {quantity} kg {item_name} (koszt: {total_cost} PLN)")

    success = sql_funcs.db_process_procurement_transaction(
        partner=sender_id,
        item_name=str(item_name),
        quantity=int(quantity),
        total_cost=float(total_cost)
    )

    if not success:
        return json.dumps({
            "status": "FAILED",
            "reason": "Błąd transakcji SQL podczas rozliczania dostawy (brak środków lub błąd bazy)."
        })

    return json.dumps({
        "status": "SUCCESS",
        "message_type": "DELIVERY_CONFIRMATION",
        "sender_id": "H1",
        "receiver_id": sender_id,
        "item_name": item_name,
        "quantity": quantity,
        "message": f"Hurtownia H1 pomyślnie odebrała i opłaciła dostawę {quantity} kg {item_name}."
    })