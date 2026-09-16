import sqlite3
import threading
from fastmcp import FastMCP
from pyngrok import ngrok
import os
from data.database import db_file
from data.models import Delivery
from pydantic import ValidationError

# inicjalizacja serwera MCP. Tworzymy instancję serwera o nazwie "Restauracja_2". Ten obiekt będzie nasłuchiwał na porcie 8000 i przyjmował połączenia od hurtowni.
mcp = FastMCP("Restauracja_2")

# Dekorator @mcp.tool() wystawia tę funkcję na zewnątrz. Dzięki temu hurtownia może zdalnie wywołać funkcję 'receive_delivery'.
@mcp.tool()
def receive_delivery(delivery_data: dict) -> str:
    """
    Odbiera sformatowany dokument dostawy (DELIVERY) w formacie JSON (zgodny z protokołem CNP).
    Automatycznie modyfikuje bazę danych: aktualizuje stan magazynowy (dodaje towar), 
    potrąca środki z konta restauracji (R1_WALLET) oraz rejestruje zdarzenie w historii transakcji.
    """
    
    try:
        dostawa = Delivery(**delivery_data) # Pydantic sprawdza, czy hurtownia przysłała poprawnego JSON-a.
    except ValidationError as e:
        return f"Błąd protokołu: Niepoprawny format dokumentacji dostawy (DELIVERY). Szczegóły: {e}"

    # Rozpakowanie zweryfikowanych danych do czytelnych zmiennych
    id_hurtowni = dostawa.sender_id
    produkt = dostawa.item.name
    ilosc = dostawa.item.quantity
    koszt_calkowity = dostawa.total_cost
    
    conn = sqlite3.connect(db_file, timeout=20.0) # Płączenie się z bazą danych
    try:
        # Menedżer kontekstu (with conn:) rozpoczyna tranzakcję ACID. Gwarantuje, że zapytania wykonają się w całości.
        with conn:
            cursor = conn.cursor()

            cursor.execute("UPDATE konto SET balans = balans - ? WHERE id = 1", (koszt_calkowity,))
            cursor.execute("UPDATE magazyn SET ilosc = ilosc + ? WHERE nazwa_produktu COLLATE NOCASE = ?", (ilosc, produkt))

            if cursor.rowcount == 0:
                cursor.execute("INSERT INTO magazyn (nazwa_produktu, ilosc, jednostka) VALUES (?, ?, 'kg')", (produkt, ilosc))

            cursor.execute(
                "INSERT INTO historia_transakcji (typ_akcji, od_kogo, produkt, ilosc, koszt) VALUES (?, ?, ?, ?, ?)",
                (f'DOSTAWA CNP (Od: {id_hurtowni})', id_hurtowni, produkt, ilosc, koszt_calkowity)
            )
            
        print(f"\n[SERWER MCP]: Przyjęto dostawę {ilosc}x {produkt} od {id_hurtowni}.") 
        return f"Potwierdzenie dla {id_hurtowni}: Towar {produkt} przyjęty, zaksięgowano {koszt_calkowity} PLN." # Zwracamy hurtowni komunikat o sukcesie
        
    except Exception as e:
        # Jeśli na jakimkolwiek etapie wystąpił błąd, baza robi automatyczny ROLLBACK
        print(f"[SERWER MCP BŁĄD]: Błąd zapisu bazy danych: {e}")
        return f"Błąd wewnętrzny kupującego (R2): {e}"
    finally:
        conn.close() # Zamykamy połączenie z bazą danych, aby nie blokować innych operacji

#def run_mcp_server():
#    ngrok_token = os.environ.get('NGROK_TOKEN')
#    if ngrok_token:
#        ngrok.set_auth_token(ngrok_token)
#    public_url = ngrok.connect(8000).public_url
#    print(f"Uruchomiono publiczny serwer MCP na {public_url}")
#    mcp.run(transport="sse", host="0.0.0.0", port=8000)
    
def run_mcp_server():
    """Uruchamia serwer MCP lokalnie na protokole SSE."""
    print("Uruchomionolokalny serwer MCP na porcie 8000 (adres: http://127.0.0.1:8000/sse)")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    run_mcp_server()