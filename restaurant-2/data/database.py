import os
import sqlite3

db_file = 'data/restauracja_2.db'
sql_file = 'data/baza_r2_projektA2A.sql'

def init_db():
    """Tworzy bazę danych tylko wtedy, gdy ona jeszcze nie istnieje."""
    # Sprawdzamy, czy plik bazy JUŻ ISTNIEJE
    if not os.path.exists(db_file):
        print("🔧 [BAZA]: Nie znaleziono pliku bazy. Tworzę nową...")
        if os.path.exists(sql_file):
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            with open(sql_file, 'r', encoding='utf-8') as file:
                cursor.executescript(file.read())
            conn.commit()
            conn.close()
            print("[BAZA]: Baza danych zainicjalizowana pomyślnie z pliku SQL.")
        else:
            print(f"[BAZA]: Błąd! Nie znaleziono pliku schematu: {sql_file}")
    else:
        print("[BAZA]: Baza danych już istnieje. Wczytuję zapisany stan.")