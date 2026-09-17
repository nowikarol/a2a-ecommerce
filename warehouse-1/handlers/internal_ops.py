import httpx
from fastapi import HTTPException
import data.sql_functions as sql_ops

def request_offer(agent_id: str, producer_url: str, item_name: str, quantity: int) -> dict:
    """Wysyła CALL_FOR_PROPOSAL do agenta Producenta przez REST."""
    order_msg = {
        "sender_id": agent_id,
        "receiver_id": "producer",
        "message_type": "CALL_FOR_PROPOSAL",
        "item": {"name": item_name, "quantity": quantity, "price": 0.0, "unit": "pcs"},
        "total_cost": 0.0,
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(producer_url, json=order_msg)
            return response.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Unable to reach Producer server: {exc}")


def accept_offer(agent_id: str, producer_url: str, item_name: str, quantity: int, price: float) -> dict:
    """Wysyła ACCEPT_PROPOSAL do Producenta, pobiera opłatę z konta i aktualizuje zapasy."""
    total_cost = round(quantity * price, 2)
    accept_msg = {
        "sender_id": agent_id,
        "receiver_id": "producer",
        "message_type": "ACCEPT_PROPOSAL",
        "item": {"name": item_name, "quantity": quantity, "price": price, "unit": "pcs"},
        "total_cost": total_cost,
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(producer_url, json=accept_msg)
            data = response.json()

            if data.get("message_type") == "DELIVERY":
                # 1. Zaksięguj wydatek
                tx_success = sql_ops.db_record_transaction(
                    transaction_partner="producer",
                    transaction_type="PROCUREMENT_PAYMENT",
                    item_name=item_name,
                    quantity=quantity,
                    total_cost=total_cost
                )
                if not tx_success:
                    raise HTTPException(status_code=400, detail="Brak wystarczających środków na koncie na pokrycie zakupu.")

                # 2. Dodaj towar
                sql_ops.db_update_stock(item_name, quantity, 'add')

            return {"status": "PURCHASE_COMPLETED", "producer_response": data}
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Unable to reach Producer server: {exc}")