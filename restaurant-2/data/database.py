import os
import sqlite3

db_file = 'data/restauracja_2.db'
sql_file = 'data/baza_r2_projektA2A.sql'

def init_db():
    """
    Tworzy bazę danych na podstawie pliku SQL, ale tylko wtedy, 
    gdy fizyczny plik bazy (.db) jeszcze nie istnieje na dysku.
    """
    if not os.path.exists(db_file):
        print("[BAZA]: Nie znaleziono pliku bazy. Tworzy się nowa...")
        if os.path.exists(sql_file):
            conn = sqlite3.connect(db_file, timeout=10.0)
            cursor = conn.cursor()
            # Włączenie trybu WAL (Write-Ahead Logging). Jest to kluczowe ustawienie dla współbieżności. Pozwala na to, aby 
            # jeden wątek zapisywał dane, podczas gdy inne wątki mogą w tym samym czasie czytać bazę.
            cursor.execute("PRAGMA journal_mode=WAL;")

            # Otwieramy plik SQL w trybie odczytu ('r') z kodowaniem UTF-8 (aby polskie znaki działały poprawnie)
            with open(sql_file, 'r', encoding='utf-8') as file:
                cursor.executescript(file.read()) # executescript pozwala wykonać cały plik SQL na raz
            conn.commit()
            conn.close()
            print("[BAZA]: Baza danych zainicjalizowana pomyślnie z pliku SQL.")
        else:
            print(f"[BAZA]: Błąd! Nie znaleziono pliku schematu: {sql_file}")
    else:
        print("[BAZA]: Baza danych już istnieje. Wczytuję zapisany stan.")