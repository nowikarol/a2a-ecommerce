# ============================== Moduł zakupowy H1 – komunikacja z serwerem Producenta F1 =========================================

import os
import httpx
from dotenv import load_dotenv
from data.models import Item, TradeMessage

load_dotenv()

PRODUCER_URL = os.getenv("PRODUCER_URL", "http://127.0.0.1:8004/mcp/sse") 

def check_producer_availability(agent_id: str, item_name: str, quantity: int, unit: str = "pcs") -> TradeMessage:
    """Wysyła zapytanie o dostępność (AVAILABILITY_REQUEST) do Producenta."""
    order_item = Item(name=item_name, quantity=quantity, unit=unit)
    msg = TradeMessage(
        sender_id=agent_id,
        receiver_id="producer",
        message_type="AVAILABILITY_REQUEST",
        item=order_item
    )
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(PRODUCER_URL, json=msg.model_dump())
            return TradeMessage(**response.json())
    except Exception as exc:
        return TradeMessage(
            sender_id="producer",
            receiver_id=agent_id,
            message_type="AVAILABILITY_RESPONSE",
            item=order_item,
            is_available=False,
            reason=f"Nie można połączyć się z serwerem producenta: {exc}"
        )


def request_producer_offer(agent_id: str, item_name: str, quantity: int, unit: str = "pcs") -> TradeMessage:
    """Wysyła zapytanie ofertowe (CALL_FOR_PROPOSAL) do Producenta."""
    order_item = Item(name=item_name, quantity=quantity, unit=unit)
    order_msg = TradeMessage(
        sender_id=agent_id,
        receiver_id="producer",
        message_type="CALL_FOR_PROPOSAL",
        item=order_item
    )
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(PRODUCER_URL, json=order_msg.model_dump())
            return TradeMessage(**response.json())
    except Exception as exc:
        return TradeMessage(
            sender_id="producer",
            receiver_id=agent_id,
            message_type="REJECT_PROPOSAL",
            item=order_item,
            reason=f"Nie można połączyć się z serwerem producenta: {exc}"
        )


def accept_producer_offer(agent_id: str, item_name: str, quantity: int, price: float, unit: str = "pcs") -> TradeMessage:
    """Wysyła akceptację oferty (ACCEPT_PROPOSAL) do Producenta."""
    total_cost = round(quantity * price, 2)
    order_item = Item(name=item_name, quantity=quantity, price=price, unit=unit)
    accept_msg = TradeMessage(
        sender_id=agent_id,
        receiver_id="producer",
        message_type="ACCEPT_PROPOSAL",
        item=order_item,
        total_cost=total_cost
    )
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(PRODUCER_URL, json=accept_msg.model_dump())
            return TradeMessage(**response.json())
    except Exception as exc:
        return TradeMessage(
            sender_id="producer",
            receiver_id=agent_id,
            message_type="REJECT_PROPOSAL",
            item=order_item,
            reason=f"Nie można połączyć się z serwerem producenta podczas akceptacji: {exc}"
        )