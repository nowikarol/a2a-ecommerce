import sqlite3
from pathlib import Path
from typing import Literal


path = Path(__file__).resolve().parent / "warehouse1.db"

def get_connection():
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # Dostęp do kolumn po nazwach
    return conn

def init_db(products_list):
    """Tworzy tabelę produktów w bazie danych SQL, jeśli nie istnieje, i wypełnia ją początkowymi danymi."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    name TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL
                )
            """)

            cur = conn.execute("SELECT COUNT(*) FROM products")
            if cur.fetchone()[0] == 0:
                conn.executemany("INSERT INTO products (name, quantity, price) VALUES (:name, :quantity, :price)", products_list)
                conn.commit()
    finally:
        conn.close()


# === Funkcje Pomocnicze ===

def db_get_product(item_name: str):
    """Pobiera informacje o produkcie z bazy na podstawie nazwy."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT price, quantity FROM products WHERE name = ?", (item_name,))
        return cursor.fetchone()
    finally:
        conn.close()


def db_update_stock(item_name: str, quantity_change: int, operation: Literal["add", "subtract"]):
    """Aktualizuje liczbę produktów w magazynie."""
    conn = get_connection()
    try:
        with conn: 
            if operation == 'subtract':
                conn.execute("UPDATE products SET quantity = MAX(0, quantity - ?) WHERE name = ?", (quantity_change, item_name))
            elif operation == 'add':
                conn.execute("UPDATE products SET quantity = quantity + ? WHERE name = ?", (quantity_change, item_name))
            conn.commit()
    finally:
        conn.close()