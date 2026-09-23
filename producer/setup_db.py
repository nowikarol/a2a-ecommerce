import sqlite3
import datetime

DB_PATH = "producer.db"


def create_tables(conn):
    cursor = conn.cursor()

    # Tabela produktów (katalog surowców, które P1 sprzedaje Hurtowniom)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS products
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       product_code
                       TEXT
                       UNIQUE
                       NOT
                       NULL,
                       name
                       TEXT
                       NOT
                       NULL,
                       unit_price
                       REAL
                       NOT
                       NULL,
                       stock_quantity
                       REAL
                       NOT
                       NULL,
                       unit
                       TEXT
                       NOT
                       NULL
                   )
                   """)

    # Tabela planu produkcji (używana WYŁĄCZNIE do check_availability)
    # Dodano UNIQUE(product_code, production_date), aby zapobiec dublowaniu wpisów
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS production_plan
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       product_code
                       TEXT
                       NOT
                       NULL,
                       production_date
                       TEXT
                       NOT
                       NULL,
                       quantity
                       REAL
                       NOT
                       NULL,
                       status
                       TEXT
                       DEFAULT
                       'planned',
                       FOREIGN
                       KEY
                   (
                       product_code
                   ) REFERENCES products
                   (
                       product_code
                   ),
                       UNIQUE
                   (
                       product_code,
                       production_date
                   )
                       )
                   """)

    # Rejestr transakcji sprzedaży (Krok 5 protokołu)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS sales_transactions
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       product_code
                       TEXT
                       NOT
                       NULL,
                       quantity
                       REAL
                       NOT
                       NULL,
                       unit_price
                       REAL
                       NOT
                       NULL,
                       total_cost
                       REAL
                       NOT
                       NULL,
                       buyer_id
                       TEXT
                       NOT
                       NULL,
                       transaction_date
                       TEXT
                       NOT
                       NULL,
                       FOREIGN
                       KEY
                   (
                       product_code
                   ) REFERENCES products
                   (
                       product_code
                   )
                       )
                   """)

    conn.commit()


def insert_sample_data(conn):
    cursor = conn.cursor()

    products = [
        ("flour", "Mąka pszenna", 2.50, 500.0, "kg"),
        ("passata", "Passata pomidorowa", 4.20, 200.0, "kg"),
        ("mozzarella", "Mozzarella w kulkach", 12.00, 100.0, "szt."),
        ("parmigiano reggiano", "Parmigiano Reggiano", 22.00, 80.0, "kg"),
        ("burrata", "Burrata", 15.00, 60.0, "szt."),
        ("buffala", "Mleko bawole", 18.00, 40.0, "kg"),
        ("prosciutto cotto", "Prosciutto cotto", 14.00, 90.0, "kg"),
        ("prosciutto crudo", "Prosciutto crudo", 20.00, 70.0, "kg"),
        ("arugula", "Rukola", 8.00, 30.0, "kg"),
        ("lamb's lettuce", "Roszponka", 9.50, 25.0, "kg"),
        ("salami", "Salami", 16.00, 50.0, "kg"),
    ]
    cursor.executemany("""
                       INSERT
                       OR IGNORE INTO products (product_code, name, unit_price, stock_quantity, unit)
        VALUES (?, ?, ?, ?, ?)
                       """, products)

    today = datetime.date.today()
    plans = [
        ("flour", (today + datetime.timedelta(days=1)).isoformat(), 100.0, "planned"),
        ("flour", (today + datetime.timedelta(days=3)).isoformat(), 200.0, "planned"),
        ("passata", (today + datetime.timedelta(days=2)).isoformat(), 50.0, "planned"),
        ("mozzarella", (today + datetime.timedelta(days=1)).isoformat(), 30.0, "planned"),
        ("parmigiano reggiano", (today + datetime.timedelta(days=4)).isoformat(), 40.0, "planned"),
        ("burrata", (today + datetime.timedelta(days=2)).isoformat(), 20.0, "planned"),
        ("buffala", (today + datetime.timedelta(days=3)).isoformat(), 25.0, "planned"),
        ("prosciutto cotto", (today + datetime.timedelta(days=5)).isoformat(), 30.0, "planned"),
        ("prosciutto crudo", (today + datetime.timedelta(days=6)).isoformat(), 20.0, "planned"),
        ("salami", (today + datetime.timedelta(days=2)).isoformat(), 15.0, "planned"),
        ("arugula", (today + datetime.timedelta(days=1)).isoformat(), 10.0, "planned"),
        ("lamb's lettuce", (today + datetime.timedelta(days=2)).isoformat(), 10.0, "planned"),
    ]

    # Resetujemy plan produkcji przed ponownym wstawieniem
    cursor.execute("DELETE FROM production_plan")

    cursor.executemany("""
        INSERT OR REPLACE INTO production_plan (product_code, production_date, quantity, status)
        VALUES (?, ?, ?, ?)
    """, plans)

    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    insert_sample_data(conn)
    conn.close()
    print(f"Baza danych '{DB_PATH}' została pomyślnie zaktualizowana i zresetowana do danych początkowych.")


if __name__ == "__main__":
    main()