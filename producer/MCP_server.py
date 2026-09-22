"""
Serwer MCP Producenta P1.

Rola w łańcuchu dostaw: WYŁĄCZNIE Sprzedający (P1 nie kupuje niczego od
innych węzłów, więc nie wystawia i nie potrzebuje `receive_delivery`).

Zgodny z: PROTOCOL_SPECIFICATION.md (Standard Protokołu Kupujący-Sprzedający).
Wystawia 3 standardowe narzędzia Sprzedającego:
    1. check_availability  -> availability-response.json
    2. request_offer       -> response-offer.json
    3. accept_offer        -> accept-offer.json (sukces) lub reject.json
"""

import datetime
import math
import sqlite3

from fastmcp import Client, FastMCP

mcp = FastMCP("Producer_P1_MCP")

DB_PATH = "producer.db"
NODE_ID = "P1"

# Mapa PEŁNYCH adresów MCP innych węzłów sieci - ustalona przez zespół.
# UWAGA: różne węzły mogą montować FastMCP pod różnymi ścieżkami
# (np. H1 wg swojego README używa /mcp/sse, nie /sse) - dlatego trzymamy
# tu kompletny URL per węzeł, a nie tylko port + sztywny sufiks.
NODE_ENDPOINTS = {
    "P1": "http://localhost:8001/sse",
    "R1": "http://localhost:8002/sse",       # TODO: potwierdzić prawdziwą ścieżkę z R1
    "R2": "http://localhost:8003/sse",       # TODO: potwierdzić prawdziwą ścieżkę z R2
    "H1": "http://127.0.0.1:8004/mcp/sse",   # potwierdzone z README H1
    "H2": "http://localhost:8005/sse",       # TODO: potwierdzić prawdziwą ścieżkę z H2 (brak README)
}
OWN_PORT = 8001

# Zasady biznesowe rabatowe (deterministyczne, bez LLM).
REGULAR_CUSTOMERS = {"H1"}
REGULAR_CUSTOMER_DISCOUNT = 0.10  # 10%

# Tolerancja przy porównywaniu kwot (grosze) - zaokrąglenia float.
MONEY_TOLERANCE = 0.01


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_node_url(node_id: str) -> str:
    if node_id not in NODE_ENDPOINTS:
        raise ValueError(f"Nieznany węzeł sieci: {node_id}")
    return NODE_ENDPOINTS[node_id]





def make_reject(sender_id: str, item_name: str, quantity) -> dict:
    return {
        "sender_id": NODE_ID,
        "receiver_id": sender_id,
        "message_type": "REJECT_PROPOSAL",
        "item": {"name": item_name, "quantity": quantity},
    }


def is_valid_quantity(quantity) -> bool:
    """Waliduje, że quantity to sensowna, dodatnia, skończona liczba.

    Odrzuca: None, stringi, bool (True/False to technicznie int w Pythonie),
    NaN/inf, zero i wartości ujemne.
    """
    return (
        isinstance(quantity, (int, float))
        and not isinstance(quantity, bool)
        and math.isfinite(quantity)
        and quantity > 0
    )


def is_valid_money(value) -> bool:
    """Waliduje, że price/total_cost to sensowna, nieujemna, skończona liczba."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


# ---------------------------------------------------------------------------
# Krok 1: Weryfikacja dostępności towaru
# ---------------------------------------------------------------------------
@mcp.tool()
def check_availability(sender_id: str, receiver_id: str, item_name: str, quantity: float) -> dict:
    """Sprawdza dostępność towaru u Producenta P1 (Krok 1 protokołu CNP).

    Dostępność liczona jest jako suma bieżącego stanu magazynowego oraz
    planowanej produkcji (status='planned'). To wartość orientacyjna dla
    kupującego - dopiero accept_offer weryfikuje FAKTYCZNY stan magazynowy.

    Args:
        sender_id: Identyfikator kupującego wysyłającego zapytanie (np. 'H1').
        receiver_id: Identyfikator odbiorcy zapytania (zawsze 'P1').
        item_name: Kod/nazwa produktu (odpowiada polu item.name w schemacie).
        quantity: Wnioskowana ilość (odpowiada polu item.quantity w schemacie).
            Musi być dodatnią, skończoną liczbą - produkty wagowe (np. mąka)
            mogą mieć ułamkowe kg.
    """
    if not is_valid_quantity(quantity):
        return {
            "sender_id": NODE_ID,
            "receiver_id": sender_id,
            "message_type": "AVAILABILITY_RESPONSE",
            "item": {"name": item_name, "quantity": quantity},
            "is_available": False,
            "available_quantity": 0,
        }

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_code, stock_quantity FROM products WHERE product_code = ?",
        (item_name,),
    )
    product = cursor.fetchone()

    if not product:
        conn.close()
        return {
            "sender_id": NODE_ID,
            "receiver_id": sender_id,
            "message_type": "AVAILABILITY_RESPONSE",
            "item": {"name": item_name, "quantity": quantity},
            "is_available": False,
            "available_quantity": 0,
        }
    conn.close()

    current_stock = float(product["stock_quantity"])


    return {
        "sender_id": NODE_ID,
        "receiver_id": sender_id,
        "message_type": "AVAILABILITY_RESPONSE",
        "item": {"name": item_name, "quantity": quantity},
        "is_available": current_stock >= quantity,
        "available_quantity": current_stock,
    }


# ---------------------------------------------------------------------------
# Krok 2: Oferta cenowa
# ---------------------------------------------------------------------------
@mcp.tool()
def request_offer(sender_id: str, receiver_id: str, item_name: str, quantity: float) -> dict:
    """Zwraca ofertę cenową (PROPOSAL) dla podanego produktu (Krok 2 protokołu CNP).

    Sprawdza, czy wnioskowana ilość znajduje się na stanie magazynowym.
    Jeśli towaru brakuje lub produkt nie istnieje, zwraca REJECT_PROPOSAL.

    Args:
        sender_id: Identyfikator kupującego składającego zapytanie ofertowe (np. 'H1').
        receiver_id: Identyfikator odbiorcy (zawsze 'P1').
        item_name: Kod/nazwa produktu.
        quantity: Wnioskowana ilość. Musi być dodatnią, skończoną liczbą.
    """
    if not is_valid_quantity(quantity):
        return make_reject(sender_id, item_name, quantity)

    conn = get_db_connection()
    cursor = conn.cursor()
    # Pobieramy unit_price ORAZ stock_quantity
    cursor.execute(
        "SELECT product_code, unit_price, stock_quantity FROM products WHERE product_code = ?",
        (item_name,),
    )
    product = cursor.fetchone()
    conn.close()

    # Jeśli brak produktu LUB stan magazynowy jest mniejszy niż żądana ilość -> REJECT
    if not product or float(product["stock_quantity"]) < quantity:
        return make_reject(sender_id, item_name, quantity)

    unit_price = float(product["unit_price"])
    total_cost = round(unit_price * quantity, 2)

    return {
        "sender_id": NODE_ID,
        "receiver_id": sender_id,
        "message_type": "PROPOSAL",
        "item": {
            "name": product["product_code"],
            "quantity": quantity,
            "price": unit_price,
        },
        "total_cost": total_cost,
    }

# ---------------------------------------------------------------------------
# Krok 3-5: Akceptacja oferty, bilansowanie bazy i dostawa
# ---------------------------------------------------------------------------
@mcp.tool()
async def accept_offer(
    sender_id: str,
    receiver_id: str,
    item_name: str,
    quantity: float,
    price: float,
    total_cost: float,
) -> dict:
    """Obsługuje akceptację oferty przez kupującego (Krok 4-5 protokołu CNP).

    Waliduje kompletność i spójność danych wejściowych, ZANIM cokolwiek
    zmieni w bazie:
        1. quantity musi być dodatnią, skończoną liczbą.
        2. price i total_cost muszą być nieujemnymi, skończonymi liczbami.
        3. price * quantity musi zgadzać się z total_cost (spójność
           wewnętrzna wiadomości od kupującego - łapie zepsute/sfałszowane
           żądania, zanim dotkniemy magazynu).
        4. sender_id musi być znanym węzłem sieci.

    Dopiero potem weryfikuje FAKTYCZNY stan magazynowy atomowo (transakcja
    SQL) i PONOWNIE przelicza cenę z aktualnego katalogu (calculate_unit_price) -
    jeśli przeliczona cena różni się od tego, co przysłał kupujący (np. bo
    zmienił się cennik albo kupujący próbował podać zaniżoną cenę), transakcja
    jest ODRZUCANA (REJECT_PROPOSAL), a nie po cichu naprawiana na cenę z
    katalogu. Dopiero gdy wszystko się zgadza: zmniejsza stan, zapisuje
    transakcję sprzedaży i wysyła delivery.json na serwer MCP kupującego.

    Args:
        sender_id: Identyfikator kupującego akceptującego ofertę (np. 'H1').
        receiver_id: Identyfikator odbiorcy (zawsze 'P1').
        item_name: Kod/nazwa produktu.
        quantity: Ilość z zaakceptowanej oferty. Musi być > 0.
        price: Cena jednostkowa z zaakceptowanej oferty.
        total_cost: Łączny koszt z zaakceptowanej oferty (musi = price * quantity).
    """
    # --- Walidacja formatu danych wejściowych (przed dotknięciem bazy) ---
    if not is_valid_quantity(quantity):
        print(f"[UWAGA] accept_offer od {sender_id}: niepoprawna quantity={quantity!r}.")
        return make_reject(sender_id, item_name, quantity)

    if not is_valid_money(price) or not is_valid_money(total_cost):
        print(f"[UWAGA] accept_offer od {sender_id}: niepoprawne price={price!r} "
              f"lub total_cost={total_cost!r}.")
        return make_reject(sender_id, item_name, quantity)

    # Spójność wewnętrzna: to, co kupujący przysłał, musi się samo ze sobą zgadzać.
    expected_total_from_buyer = round(price * quantity, 2)
    if abs(expected_total_from_buyer - total_cost) > MONEY_TOLERANCE:
        print(f"[UWAGA] accept_offer od {sender_id}: price*quantity="
              f"{expected_total_from_buyer} nie zgadza się z przysłanym "
              f"total_cost={total_cost}. Żądanie odrzucone jako niespójne.")
        return make_reject(sender_id, item_name, quantity)

    # Walidacja odbiorcy PRZED jakąkolwiek zmianą w bazie - inaczej moglibyśmy
    # zdjąć towar ze stanu i zapisać sprzedaż na rzecz węzła, do którego i tak
    # nie da się potem wysłać dostawy.
    if sender_id not in NODE_ENDPOINTS:
        print(f"[UWAGA] Odrzucono accept_offer od nieznanego węzła: {sender_id}")
        return make_reject(sender_id, item_name, quantity)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT stock_quantity, unit_price FROM products WHERE product_code = ?",
            (item_name,),
        )
        product = cursor.fetchone()

        # Uwaga: sprawdzamy WYŁĄCZNIE fizyczny stock_quantity, nie
        # planowaną produkcję - to tutaj może wystąpić race condition
        # opisany w Kroku 4 specyfikacji.
        if not product or float(product["stock_quantity"]) < quantity:
            conn.rollback()
            conn.close()
            return make_reject(sender_id, item_name, quantity)

        # Przeliczamy cenę SAMODZIELNIE z aktualnego katalogu i porównujemy
        # z tym, co przysłał kupujący. Przy niezgodności - ODRZUCAMY całą
        # transakcję (nie modyfikujemy magazynu), zamiast po cichu rozliczać
        # po innej cenie niż ta, na którą kupujący faktycznie się zgodził.
        confirmed_price = float(product["unit_price"])
        confirmed_total_cost = round(confirmed_price * quantity, 2)

        price_matches = abs(confirmed_price - price) <= MONEY_TOLERANCE
        total_matches = abs(confirmed_total_cost - total_cost) <= MONEY_TOLERANCE

        if not price_matches or not total_matches:
            conn.rollback()
            conn.close()
            print(f"[UWAGA] {sender_id} próbował zaakceptować ofertę niezgodną "
                  f"z aktualnym katalogiem (przysłano price={price}, "
                  f"total_cost={total_cost}; katalog daje price={confirmed_price}, "
                  f"total_cost={confirmed_total_cost}). Transakcja odrzucona - "
                  f"kupujący powinien wywołać request_offer ponownie.")
            return make_reject(sender_id, item_name, quantity)

        cursor.execute(
            "UPDATE products SET stock_quantity = stock_quantity - ? WHERE product_code = ?",
            (quantity, item_name),
        )
        cursor.execute(
            """INSERT INTO sales_transactions
               (product_code, quantity, unit_price, total_cost, buyer_id, transaction_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_name, quantity, confirmed_price, confirmed_total_cost, sender_id,
             datetime.datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    delivery_message = {
        "sender_id": NODE_ID,
        "receiver_id": sender_id,
        "message_type": "DELIVERY",
        "item": {"name": item_name, "quantity": quantity, "price": confirmed_price},
        "total_cost": confirmed_total_cost,
    }

    try:
        buyer_url = get_node_url(sender_id)
        async with Client(buyer_url) as buyer_client:
            await buyer_client.call_tool("receive_delivery", arguments=delivery_message)
    except Exception as exc:
        # Towar już fizycznie zdjęty ze stanu i transakcja zapisana u nas -
        # tylko powiadomienie kupującego się nie powiodło (np. jego serwer offline).
        print(f"[UWAGA] Sprzedaż zapisana, ale nie udało się dostarczyć "
              f"delivery.json do {sender_id}: {exc}")

    return {
        "sender_id": NODE_ID,
        "receiver_id": sender_id,
        "message_type": "ACCEPT_PROPOSAL",
        "item": {"name": item_name, "quantity": quantity, "price": confirmed_price},
        "total_cost": confirmed_total_cost,
    }


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=OWN_PORT)