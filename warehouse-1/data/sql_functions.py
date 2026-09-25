import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

db_path = Path(__file__).resolve().parent/ "warehouse1.db"

def get_connection():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(products: List[Dict[str, Any]]):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                quantity INTEGER NOT NULL,
                unit TEXT NOT NULL DEFAULT 'pcs',
                price REAL NOT NULL,
                min_threshold REAL NOT NULL DEFAULT 20.0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                partner TEXT NOT NULL,
                type TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_cost REAL NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO account (id, balance) VALUES (1, 10000.0)")
        
        for p in products:
            cursor.execute("""
                INSERT OR IGNORE INTO products (name, quantity, unit, price, min_threshold)
                VALUES (?, ?, ?, ?, ?)
            """, (
                p['name'].lower().strip(), 
                p['quantity'], 
                p.get('unit', 'pcs'), 
                p['price'], 
                p.get('min_threshold', 20.0)  # minimalny próg dla produktów na stanie, domyślnie 20
            ))
        conn.commit()

def db_get_product(item_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    clean_name = item_name.strip().lower()
    
    cursor.execute(
        "SELECT name, quantity, unit, price, min_threshold FROM products WHERE LOWER(TRIM(name)) = ?", 
        (clean_name,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "name": row[0],
            "quantity": float(row[1]),
            "unit": row[2],
            "price": float(row[3]),
            "min_threshold": float(row[4])
        }
    return None

def db_get_all_products() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, quantity, unit, price, min_threshold FROM products")
        return [dict(row) for row in cursor.fetchall()]

def db_get_balance() -> float:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM account WHERE id = 1")
        row = cursor.fetchone()
        return row['balance'] if row else 0.0

def db_process_sale_transaction(partner: str, item_name: str, quantity: int, total_cost: float) -> bool:
    """Proces sprzedaży: odjęcie towaru z magazynu, dodanie środków na konto oraz zapis transakcji."""
    clean_name = item_name.lower().strip()
    with get_connection() as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT quantity FROM products WHERE LOWER(name) = ?", (clean_name,))
            row = cursor.fetchone()
            if not row or row['quantity'] < quantity:
                return False

            new_qty = row['quantity'] - quantity
            cursor.execute("UPDATE products SET quantity = ? WHERE LOWER(name) = ?", (new_qty, clean_name))
            cursor.execute("UPDATE account SET balance = balance + ? WHERE id = 1", (total_cost,))
            cursor.execute("""
                INSERT INTO transactions (partner, type, item_name, quantity, total_cost)
                VALUES (?, 'SALE', ?, ?, ?)
            """, (partner, clean_name, quantity, total_cost))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False

def db_process_procurement_transaction(partner: str, item_name: str, quantity: int, total_cost: float) -> bool:
    """Proces zakupu: dodanie towaru do magazynu, odjęcie środków z konta oraz zapis transakcji."""
    clean_name = item_name.lower().strip()
    with get_connection() as conn:
        try:
            cursor = conn.cursor()
            
            cursor.execute("SELECT balance FROM account WHERE id = 1")
            balance_row = cursor.fetchone()
            if not balance_row or balance_row['balance'] < total_cost:
                return False

            # aktualizacja ilości produktu w magazynie
            cursor.execute("SELECT quantity FROM products WHERE LOWER(name) = ?", (clean_name,))
            product_row = cursor.fetchone()
            if not product_row:
                return False

            new_qty = product_row['quantity'] + quantity

            cursor.execute("UPDATE products SET quantity = ? WHERE LOWER(name) = ?", (new_qty, clean_name))
            cursor.execute("UPDATE account SET balance = balance - ? WHERE id = 1", (total_cost,))
            cursor.execute("""
                INSERT INTO transactions (partner, type, item_name, quantity, total_cost)
                VALUES (?, 'PROCUREMENT_PAYMENT', ?, ?, ?)
            """, (partner, clean_name, quantity, total_cost))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False