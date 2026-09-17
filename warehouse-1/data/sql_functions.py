import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal

# Ścieżka: data/
path = Path(__file__).parent / "warehouse1.db"


def get_connection() -> sqlite3.Connection:
    """Tworzy i zwraca połączenie z bazą danych z obsługą dostępu przez nazwy kolumn."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(products_data: List[Dict[str, Any]], initial_balance: float = 10000.0) -> None:
    """Inicjalizuje schemat bazy danych (produkty, portfel, transakcje) oraz dane startowe."""
    conn = get_connection()
    try:
        with conn:
            # 1. Tabela produktów
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    name TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL CHECK (quantity >= 0),
                    unit TEXT NOT NULL,
                    price REAL NOT NULL CHECK (price >= 0)
                )
            """)

            # 2. Tabela portfela (CHECK wymusza dokładnie 1 rekord)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'PLN'
                )
            """)

            # 3. Tabela historii transakcji
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    transaction_partner TEXT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    total_cost REAL NOT NULL
                )
            """)

            # Inicjalizacja produktów, jeśli tabela jest pusta
            cursor = conn.execute("SELECT COUNT(*) as count FROM products")
            if cursor.fetchone()["count"] == 0:
                for p in products_data:
                    conn.execute(
                        """
                        INSERT INTO products (name, quantity, unit, price)
                        VALUES (?, ?, ?, ?)
                        """,
                        (p["name"], p["quantity"], p.get("unit", "pcs"), p["price"])
                    )

            # Inicjalizacja portfela, jeśli jest pusty
            cursor = conn.execute("SELECT COUNT(*) as count FROM account")
            if cursor.fetchone()["count"] == 0:
                conn.execute("INSERT INTO account (id, balance) VALUES (1, ?)", (initial_balance,))
    finally:
        conn.close()


# =====================================================================
# OPERACJE NA PRODUKTACH I MAGAZYNIE
# =====================================================================

def db_get_product(item_name: str) -> Optional[Dict[str, Any]]:
    """Pobiera pojedynczy produkt z bazy na podstawie nazwy."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT name, quantity, unit, price FROM products WHERE name = ?", (item_name,))
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "name": row["name"], 
            "quantity": row["quantity"], 
            "unit": row["unit"], 
            "price": row["price"]
        }
    finally:
        conn.close()


def db_get_all_products() -> List[Dict[str, Any]]:
    """Pobiera listę wszystkich produktów."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT name, quantity, unit, price FROM products")
        rows = cursor.fetchall()
        return [
            {
                "name": r["name"], 
                "quantity": r["quantity"], 
                "unit": r["unit"], 
                "price": r["price"]
            } 
            for r in rows
        ]
    finally:
        conn.close()


def db_update_stock(item_name: str, quantity: int, operation: Literal["subtract", "add"] = "subtract") -> bool:
    """
    Aktualizuje stan magazynowy produktu.

    Arguments:
    --------------
    - item_name: nazwa produktu
    - quantity: ilość do dodania lub odjęcia
    - operation: 'subtract' (odjęcie ze stanu) lub 'add' (dodanie do stanu)
    """
    conn = get_connection()
    try:
        with conn:
            if operation == "subtract":
                cursor = conn.execute("SELECT quantity FROM products WHERE name = ?", (item_name,))
                row = cursor.fetchone()
                if not row or row["quantity"] < quantity:
                    return False
                conn.execute("UPDATE products SET quantity = quantity - ? WHERE name = ?", (quantity, item_name))
            elif operation == "add":
                conn.execute("UPDATE products SET quantity = quantity + ? WHERE name = ?", (quantity, item_name))
            return True
    finally:
        conn.close()


# =====================================================================
# OPERACJE FINANSE I TRANSAKCJE
# =====================================================================

def db_get_balance() -> float:
    """Pobiera aktualny stan konta."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT balance FROM account WHERE id = 1")
        row = cursor.fetchone()
        return row["balance"] if row else 0.0
    finally:
        conn.close()


def db_record_transaction(transaction_partner: str, transaction_type: Literal["SALE", "PROCUREMENT_PAYMENT"], 
                          item_name: str, quantity: int, total_cost: float) -> bool:
    """
    Wykonuje transakcję finansową:
    1. Sprawdza i aktualizuje saldo w tabeli 'account'.
    2. Zapisuje historię transakcji w tabeli 'transactions'.
    """
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("SELECT balance FROM account WHERE id = 1")
            row = cursor.fetchone()
            current_balance = row["balance"] if row else 0.0

            if transaction_type == "SALE":
                new_balance = current_balance + total_cost
            elif transaction_type == "PROCUREMENT_PAYMENT":
                if current_balance < total_cost:
                    return False  # Brak środków na koncie
                new_balance = current_balance - total_cost
            else:
                raise ValueError(f"Nieznany typ transakcji: {transaction_type}")

            # 1. Aktualizacja salda
            conn.execute("UPDATE account SET balance = ? WHERE id = 1", (new_balance,))

            # 2. Rejestracja w historii transakcji
            conn.execute(
                """
                INSERT INTO transactions 
                (transaction_partner, transaction_type, item_name, quantity, total_cost)
                VALUES (?, ?, ?, ?, ?)
                """,
                (transaction_partner, transaction_type, item_name, quantity, total_cost)
            )

            return True
    finally:
        conn.close()


def db_get_transaction_history() -> List[Dict[str, Any]]:
    """Pobiera historię wszystkich transakcji od najnowszych."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, timestamp, transaction_partner, transaction_type, item_name, quantity, total_cost
            FROM transactions 
            ORDER BY id DESC
            """
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()