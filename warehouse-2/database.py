import sqlite3
from pathlib import Path


DATABASE = Path(__file__).parent / "warehouse2.db"


products= [("Flour", 50, 4.00, "kg"),
            ("Passata", 75, 6.00, "kg"),
            ("Mozzarella", 60, 14.50, "kg"),
            ("Parmigiano reggiano", 80, 32.50, "kg"),
            ("Burrata", 30, 30.00, "kg"),
            ("Buffala", 200, 20.00, "kg"),
            ("Prosciutto cotto", 100, 24.50, "kg"),
            ("Prosciutto crudo", 150, 20.50, "kg"),
            ("Arugula", 100, 15.00, "kg"),
            ("Lamb's lettuce", 80, 11.00, "kg"),
            ("Salami", 120, 21.50, "kg") ]

def tables(connection:sqlite3.Connection,products:list):
    '''
    Creates tabled and fill them with data
    '''
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS warehouse2(
                name TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                price REAL NOT NULL CHECK (price >= 0),
                unit TEXT NOT NULL
            )
            """
        )
        cursor.executemany(
            """
            INSERT  OR IGNORE INTO warehouse2 (name, quantity, price, unit)
            VALUES (?, ?, ?, ?)
            """, products)
        
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_warehouse2  (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('INCOME', 'EXPENSE')),
                ballance REAL NOT NULL)
            """)

        cursor.execute(
            """
            INSERT OR IGNORE INTO wallet_warehouse2 (sender_id, receiver_id, type, ballance)
            VALUES ("SYSTEM", "H2", "INCOME",1000.00)
            """)

        connection.commit()
    finally:
        connection.close()

def start_database():
    connection = sqlite3.connect(DATABASE)
    tables(connection,products)
    connection.close()

if __name__ == "__main__":
    start_database()
