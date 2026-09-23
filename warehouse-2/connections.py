import sqlite3
from scheam import Item
from pathlib import Path


DATABASE = Path(__file__).parent / "warehouse2.db"

def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def get_product(item: str):
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT name, quantity, price
            FROM warehouse2 WHERE name = ?
            """,(item,),)
        product = cursor.fetchone()
        if product is None:
            return None
        return Item(name=product,
                    quantity=0,
                    price=0)
    finally:
        cursor.close()
        connection.close()
