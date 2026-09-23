from typing import List, Dict, Any
from langchain_core.tools import tool
import data.sql_functions as sql_funcs
from network.client import check_producer_availability, request_producer_proposal, accept_producer_proposal


@tool
def get_warehouse_stock() -> List[Dict[str, Any]]:
    """Zwraca aktualny stan magazynowy Hurtowni H1."""
    return sql_funcs.db_get_all_products()


@tool
def check_balance() -> Dict[str, float]:
    """Zwraca stan finansowy na koncie Hurtowni H1 w PLN."""
    return {"balance": sql_funcs.db_get_balance()}


@tool
async def check_producer_stock(item_name: str, quantity: float) -> Dict[str, Any]:
    """Sprawdza czy Producent posiada na stanie wymaganą ilość surowca."""
    res = await check_producer_availability(buyer_id="H1", item_name=item_name, quantity=quantity)
    is_avail = res.get("is_available", False)
    avail_qty = res.get("available_quantity", 0.0)
    
    if is_avail:
        return {"status": "SUCCESS", "message": f"Producent posiada na stanie {quantity} kg towaru {item_name}."}
    else:
        return {"status": "FAILED", "message": f"Producent nie posiada wystarczającej ilości. Dostępność: {avail_qty} kg."}


@tool
async def get_producer_proposal(item_name: str, quantity: float) -> Dict[str, Any]:
    """Wysyła zapytanie ofertowe (CALL_FOR_PROPOSAL) do Producenta i zwraca wycenę."""
    res = await request_producer_proposal(buyer_id="H1", item_name=item_name, quantity=quantity)
    
    if res.get("message_type") == "PROPOSAL":
        item_data = res.get("item", {})
        price = float(item_data.get("price", 0.0))
        total_cost = float(res.get("total_cost", price * quantity))
        
        return {
            "status": "SUCCESS",
            "item_name": item_name,
            "quantity": quantity,
            "unit_price": price,
            "total_cost": total_cost,
            "message": f"Otrzymano ofertę: cena {price} PLN, łączny koszt: {total_cost} PLN."
        }
    else:
        reason = res.get("reason", "Producent odrzucił zapytanie ofertowe.")
        return {"status": "FAILED", "reason": reason}


@tool
async def finalize_producer_purchase(item_name: str, quantity: float, unit_price: float, total_cost: float) -> Dict[str, Any]:
    """Akceptuje ofertę (ACCEPT_PROPOSAL) u Producenta. Płatność/przyjęcie towaru nastąpią po fizycznym otrzymaniu dostawy."""
    balance = sql_funcs.db_get_balance()
    if balance < total_cost:
        return {
            "status": "FAILED",
            "reason": f"Brak wystarczających środków na koncie H1. Wymagane: {total_cost} PLN, dostępne: {balance} PLN."
        }

    # Wysyłamy akceptację oferty przez MCP do Producenta
    res = await accept_producer_proposal(
        buyer_id="H1",
        item_name=item_name,
        quantity=quantity,
        price=unit_price,
        total_cost=total_cost
    )

    if res.get("message_type") == "ACCEPT_PROPOSAL" or res.get("status") in ["SUCCESS", "ACCEPTED"]:
        return {
            "status": "ACCEPTED",
            "item_name": item_name,
            "quantity": quantity,
            "total_cost": total_cost,
            "message": f"Pomyślnie zaakceptowano ofertę na {quantity} kg {item_name} za {total_cost} PLN. Oczekiwanie na dostawę."
        }
    else:
        reason = res.get("reason", "Producent odrzucił akceptację oferty.")
        return {"status": "REJECTED", "reason": reason}