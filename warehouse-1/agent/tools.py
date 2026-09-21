from typing import List, Dict, Any
from langchain_core.tools import tool
import data.sql_functions as sql_funcs
from network.client import request_producer_offer, accept_producer_offer

@tool
def get_warehouse_stock() -> List[Dict[str, Any]]:
    """Zwraca aktualny stan magazynowy Hurtowni H1."""
    return sql_funcs.db_get_all_products()

@tool
def check_balance() -> Dict[str, float]:
    """Zwraca stan finansowy na koncie Hurtowni H1."""
    return {"balance": sql_funcs.db_get_balance()}

@tool
def procure_product_from_producer(item_name: str, quantity: int) -> Dict[str, Any]:
    """
    Kupuje towary u Producenta F1:
    1. Pobiera wycenę.
    2. Sprawdza finanse.
    3. Finalizuje transakcję, pobiera środki z konta i aktualizuje magazyn.
    """
    agent_id = "H1"
    product = sql_funcs.db_get_product(item_name)
    unit = product["unit"] if product else "pcs"

    # 1. Pobranie wyceny
    proposal = request_producer_offer(agent_id, item_name, quantity, unit)
    if proposal.message_type != "PROPOSAL":
        return {
            "status": "FAILED",
            "reason": proposal.reason or "Producent odrzucił zapytanie.",
            "details": proposal.model_dump()
        }

    total_cost = proposal.total_cost
    current_balance = sql_funcs.db_get_balance()

    # 2. Sprawdzenie salda
    if current_balance < total_cost:
        return {
            "status": "REJECTED",
            "reason": "Brak wystarczających środków na zakupy u producenta.",
            "total_cost": total_cost,
            "current_balance": current_balance
        }

    # 3. Akceptacja i rejestracja zakupu
    price = proposal.item.price
    result = accept_producer_offer(agent_id, item_name, quantity, price, unit)

    if result.message_type in ["DELIVERY", "ACCEPT_PROPOSAL"]:
        tx_success = sql_funcs.db_record_transaction(
            transaction_partner="producer",
            transaction_type="PROCUREMENT_PAYMENT",
            item_name=item_name,
            quantity=quantity,
            total_cost=total_cost
        )
        if not tx_success:
            return {"status": "FAILED", "reason": "Błąd podczas rejestracji transakcji zakupu."}

        sql_funcs.db_update_stock(item_name, quantity, 'add')
        return {"status": "PURCHASE_COMPLETED", "details": result.model_dump(), "total_cost": total_cost}

    return {"status": "REJECTED_BY_PRODUCER", "details": result.model_dump()}