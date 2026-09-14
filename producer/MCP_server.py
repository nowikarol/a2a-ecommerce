import sqlite3
from fastmcp import FastMCP

mcp = FastMCP("Factory_Catalog_MCP")
DB_PATH = "factory.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def get_preliminary_price(
    product_code: str,
    quantity: int,
    sender_id: str = "H1",
    receiver_id: str = "F1",
) -> dict:
    """Oblicza wstępną wycenę dla podanego produktu i ilości.

        Pobiera cenę jednostkową z katalogu i generuje ofertę (PROPOSAL) z całkowitym kosztem.
        W przypadku braku produktu w bazie zwraca odrzucenie zapytania (REJECT_PROPOSAL).

        Args:
            product_code: Kod lub identyfikator produktu w bazie.
            quantity: Liczba zamawianych sztuk.
            sender_id: Identyfikator nadawcy wiadomości (domyślnie 'H1').
            receiver_id: Identyfikator odbiorcy wiadomości (domyślnie 'R1').
        """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_code, unit_price FROM products WHERE product_code = ?",
        (product_code,),
    )
    product = cursor.fetchone()
    conn.close()

    if not product:
        return {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": "REJECT_PROPOSAL",
            "item": {"name": product_code, "quantity": int(quantity)},
        }

    unit_price = float(product["unit_price"])
    return {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "message_type": "PROPOSAL",
        "item": {
            "name": product["product_code"],
            "quantity": int(quantity),
            "price": unit_price,
        },
        "total_cost": round(unit_price * quantity, 2),

    }

@mcp.tool()
def get_service_directory() -> dict:
    """Zwraca mapę punktów końcowych (endpoints) fabryki F1, opisując co gdzie wysyłać."""
    return {
        "supplier_id": "F1",
        "description": "System handlowo-magazynowy Fabryki F1",
        "endpoints": {
            "mcp_direct_db": {
                "path": "/sse",
                "protocol": "MCP (Server-Sent Events)",
                "purpose": "Surowy odczyt z bazy danych",
                "when_to_use": "Użyj, gdy chcesz tylko sprawdzić oficjalną cenę katalogową lub sprawdzić stany magazynowe bez negocjacji.",
            },
            "a2a_negotiation_agent": {
                "path": "/a2a/rfq",
                "protocol": "HTTP POST (JSON)",
                "purpose": "Autonomiczny agent handlowy (AI Gemini)",
                "when_to_use": "Użyj, gdy chcesz wynegocjować cenę, wysłać ofertę (CALL_FOR_PROPOSAL) lub uzyskać rabat handlowy.",
            },
        },
    }
@mcp.tool()
def check_availability(
    product_code: str,
    quantity: int,
    sender_id: str = "H1",
    receiver_id: str = "R1",
) -> dict:
    """Sprawdza dostępność magazynową i planowaną produkcję danego produktu.

        Uwzględnia sumę obecnego stanu magazynowego oraz planowanej produkcji.
        Zwraca ofertę (PROPOSAL) z maksymalną dostępną ilością (nie większą niż wnioskowana)
        lub odmowę (REJECT_PROPOSAL), jeśli produkt jest niedostępny.

        Args:
            product_code: Kod lub identyfikator produktu w bazie.
            quantity: Wnioskowana ilość sztuk.
            sender_id: Identyfikator nadawcy wiadomości (domyślnie 'H1').
            receiver_id: Identyfikator odbiorcy wiadomości (domyślnie 'R1').
        """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_code, unit_price, stock_quantity FROM products WHERE product_code = ?",
        (product_code,),
    )
    product = cursor.fetchone()

    if not product:
        conn.close()
        return {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": "REJECT_PROPOSAL",
            "item": {"name": product_code, "quantity": int(quantity)},
        }

    cursor.execute(
        "SELECT SUM(quantity) as planned_quantity FROM production_plan WHERE product_code = ? AND status = 'planned'",
        (product_code,),
    )
    plan_row = cursor.fetchone()
    conn.close()

    current_stock = float(product["stock_quantity"])
    planned_stock = (
        float(plan_row["planned_quantity"])
        if plan_row and plan_row["planned_quantity"]
        else 0.0
    )
    total_available = int(current_stock + planned_stock)

    if total_available <= 0:
        return {
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": "REJECT_PROPOSAL",
            "item": {"name": product["product_code"], "quantity": int(quantity)},
        }

    offered_quantity = min(int(quantity), total_available)
    unit_price = float(product["unit_price"])

    return {
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "message_type": "PROPOSAL",
        "item": {
            "name": product["product_code"],
            "quantity": offered_quantity,
            "price": unit_price,
        },
        "total_cost": round(unit_price * offered_quantity, 2),
    }


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)