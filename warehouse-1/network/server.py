# ============================= Serwer FastMCP do obsługi zamówień przychodzących z Restauracji ================================

import logging
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from data.models import Item, TradeMessage

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from data.sql_functions import db_get_product, db_process_sale_transaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("H1_SERVER_MCP")

AGENT_ID = "H1"
mcp = FastMCP("Warehouse_1")

@mcp.tool()
def check_availability(receiver_id: str, item: Item) -> dict:
    item_name = item.name.strip()
    req_qty = item.quantity
    
    row = db_get_product(item_name)
    available_qty = row["quantity"] if row else 0
    is_available = available_qty >= req_qty
    actual_unit = row["unit"] if row else item.unit

    response = TradeMessage(
        sender_id=AGENT_ID,
        receiver_id=receiver_id,
        message_type="AVAILABILITY_RESPONSE",
        item=Item(name=item_name, quantity=req_qty, unit=actual_unit),
        is_available=is_available,
        available_quantity=available_qty
    )
    return response.model_dump()

@mcp.tool()
def request_offer(receiver_id: str, item: Item) -> dict:
    item_name = item.name.strip()
    row = db_get_product(item_name)
    
    if not row or row["quantity"] < item.quantity:
        response = TradeMessage(
            sender_id=AGENT_ID,
            receiver_id=receiver_id,
            message_type="REJECT_PROPOSAL",
            item=Item(name=item_name, quantity=item.quantity, unit=item.unit),
            reason="Brak wystarczającej ilości w magazynie lub niedostępny produkt."
        )
        return response.model_dump()

    unit_price = row["price"]
    total_cost = round(item.quantity * unit_price, 2)

    offered_item = Item(name=item_name, quantity=item.quantity, unit=row["unit"], price=unit_price)
    response = TradeMessage(
        sender_id=AGENT_ID,
        receiver_id=receiver_id,
        message_type="PROPOSAL",
        item=offered_item,
        total_cost=total_cost
    )
    return response.model_dump()

@mcp.tool()
def accept_offer(receiver_id: str, item: Item, total_cost: float, sender_id: str = "R2") -> dict:
    item_name = item.name.strip()
    partner = sender_id if (receiver_id == AGENT_ID or not sender_id) else receiver_id
    row = db_get_product(item_name)
    actual_unit = row["unit"] if row else item.unit

    # Wykonanie transakcji w jednej operacji SQL
    success = db_process_sale_transaction(
        partner=partner,
        item_name=item_name,
        quantity=item.quantity,
        total_cost=total_cost
    )

    if not success:
        return TradeMessage(
            sender_id=AGENT_ID,
            receiver_id=partner,
            message_type="REJECT_PROPOSAL",
            item=Item(name=item_name, quantity=item.quantity, unit=actual_unit),
            reason="Transakcja odrzucona: brak towaru lub błąd bazy danych."
        ).model_dump()

    confirmed_item = Item(
        name=item_name,
        quantity=item.quantity,
        unit=actual_unit,
        price=item.price if item.price > 0 else (row["price"] if row else 0.0)
    )

    return TradeMessage(
        sender_id=AGENT_ID,
        receiver_id=partner,
        message_type="ACCEPT_PROPOSAL",
        item=confirmed_item,
        total_cost=total_cost
    ).model_dump()