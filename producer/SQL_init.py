import sqlite3
import datetime

DB_PATH = "factory.db"

def create_tables(conn):
    cursor = conn.cursor()
    # Tabela produktów
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            unit_price REAL NOT NULL,
            stock_quantity REAL NOT NULL,
            unit TEXT NOT NULL
        )
    """)
    # Tabela planu produkcji
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS production_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_code TEXT NOT NULL,
            production_date TEXT NOT NULL,
            quantity REAL NOT NULL,
            status TEXT DEFAULT 'planned',
            FOREIGN KEY (product_code) REFERENCES products (product_code)
        )
    """)
    conn.commit()

def insert_sample_data(conn):
    cursor = conn.cursor()
    # Produkty
    products = [
        ("flour", "Mąka pszenna", 2.50, 500.0, "kg"),
        ("passata", "Passata pomidorowa", 4.20, 200.0, "kg"),
        ("mozzarella", "Mozzarella w kulkach", 12.00, 100.0, "szt."),
        ("parmigiano_reggiano", "Parmigiano Reggiano", 22.00, 80.0, "kg"),
        ("burrata", "Burrata", 15.00, 60.0, "szt."),
        ("buffala", "Mleko bawole", 18.00, 40.0, "kg"),
        ("prosciutto_cotto", "Prosciutto cotto", 14.00, 90.0, "kg"),
        ("prosciutto_crudo", "Prosciutto crudo", 20.00, 70.0, "kg"),
        ("arugula", "Rukola", 8.00, 30.0, "kg"),
        ("lambs_lettuce", "Roszponka", 9.50, 25.0, "kg"),
        ("salami", "Salami", 16.00, 50.0, "kg"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO products (product_code, name, unit_price, stock_quantity, unit)
        VALUES (?, ?, ?, ?, ?)
    """, products)

    # Plan produkcji – przykładowe wpisy na najbliższe dni
    today = datetime.date.today()
    plans = [
        ("flour", (today + datetime.timedelta(days=1)).isoformat(), 100.0, "planned"),
        ("flour", (today + datetime.timedelta(days=3)).isoformat(), 200.0, "planned"),
        ("passata", (today + datetime.timedelta(days=2)).isoformat(), 50.0, "planned"),
        ("mozzarella", (today + datetime.timedelta(days=1)).isoformat(), 30.0, "planned"),
        ("parmigiano_reggiano", (today + datetime.timedelta(days=4)).isoformat(), 40.0, "planned"),
        ("burrata", (today + datetime.timedelta(days=2)).isoformat(), 20.0, "planned"),
        ("buffala", (today + datetime.timedelta(days=3)).isoformat(), 25.0, "planned"),
        ("prosciutto_cotto", (today + datetime.timedelta(days=5)).isoformat(), 30.0, "planned"),
        ("prosciutto_crudo", (today + datetime.timedelta(days=6)).isoformat(), 20.0, "planned"),
        ("salami", (today + datetime.timedelta(days=2)).isoformat(), 15.0, "planned"),
        ("arugula", (today + datetime.timedelta(days=1)).isoformat(), 10.0, "planned"),
        ("lambs_lettuce", (today + datetime.timedelta(days=2)).isoformat(), 10.0, "planned"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO production_plan (product_code, production_date, quantity, status)
        VALUES (?, ?, ?, ?)
    """, plans)

    conn.commit()

def main():
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    insert_sample_data(conn)
    conn.close()
    print(f"Baza danych '{DB_PATH}' została utworzona z przykładowymi danymi.")

if __name__ == "__main__":
    main()