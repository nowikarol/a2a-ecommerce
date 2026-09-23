# ============================== Moduł klient MCP (H1 -> P1) =========================================

import os
import json
import logging
from typing import Any, Dict
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

PRODUCER_URL = os.getenv("PRODUCER_URL", "http://127.0.0.1:8001/sse")
PRODUCER_ID = "P1"

logger = logging.getLogger("mcp_h1_client")


async def call_producer_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Wywołuje narzędzie MCP Producenta i zwraca odpowiedź w formacie JSON."""
    try:
        async with sse_client(PRODUCER_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                
                if not result.content:
                    return {"status": "FAILED", "reason": "Brak odpowiedzi z narzędzia MCP Producenta"}
                
                raw_text = result.content[0].text
                return json.loads(raw_text) if isinstance(raw_text, str) else raw_text
    except Exception as e:
        logger.error(f"Błąd komunikacji MCP z Producentem ({tool_name}): {e}")
        return {"status": "FAILED", "reason": f"Nie można połączyć się z serwerem producenta: {e}"}


async def check_producer_availability(buyer_id: str, item_name: str, quantity: float) -> dict:
    """KROK 1: Wywołuje tool 'check_availability' u Producenta."""
    return await call_producer_tool(
        "check_availability",
        {
            "sender_id": buyer_id,
            "receiver_id": PRODUCER_ID,
            "item_name": item_name,
            "quantity": float(quantity)
        }
    )


async def request_producer_proposal(buyer_id: str, item_name: str, quantity: float) -> dict:
    """KROK 2: Wywołuje tool 'request_offer' u Producenta."""
    return await call_producer_tool(
        "request_offer",
        {
            "sender_id": buyer_id,
            "receiver_id": PRODUCER_ID,
            "item_name": item_name,
            "quantity": float(quantity)
        }
    )


async def accept_producer_proposal(buyer_id: str, item_name: str, quantity: float, price: float, total_cost: float) -> dict:
    """KROK 4: Wywołuje tool 'accept_offer' u Producenta."""
    return await call_producer_tool(
        "accept_offer",
        {
            "sender_id": buyer_id,
            "receiver_id": PRODUCER_ID,
            "item_name": item_name,
            "quantity": float(quantity),
            "price": float(price),
            "total_cost": float(total_cost)
        }
    )