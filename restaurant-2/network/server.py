import sqlite3
import threading
from fastmcp import FastMCP
from pyngrok import ngrok
import os
from data.database import db_file

mcp = FastMCP("Restauracja_2")

@mcp.tool()
def accept_delivery(produkt: str, ilosc: float, koszt_calkowity: float, id_hurtowni: str, nr_faktury: str = "BRAK") -> str:
    """
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("UPDATE konto SET balans = balans - ? WHERE id = 1", (koszt_calkowity,))
    cursor.execute("UPDATE magazyn SET ilosc = ilosc + ? WHERE nazwa_produktu COLLATE NOCASE = ?", (ilosc, produkt))

    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO magazyn (nazwa_produktu, ilosc, jednostka) VALUES (?, ?, 'kg')", (produkt, ilosc))

    cursor.execute("INSERT INTO historia_transakcji (typ_akcji, od_kogo, produkt, ilosc, koszt) VALUES (?, ?, ?, ?, ?)",
                   (f'DOSTAWA (FV: {nr_faktury})', id_hurtowni, produkt, ilosc, koszt_calkowity))
    conn.commit()
    conn.close()

    print(f"\n Przyjęto {ilosc} {produkt} od {id_hurtowni}.")
    return f"Potwierdzenie dla {id_hurtowni}: Towar {produkt} przyjęty, faktura {nr_faktury} zaksięgowana."

def run_mcp_server():
    ngrok_token = os.environ.get('NGROK_TOKEN')
    if ngrok_token:
        ngrok.set_auth_token(ngrok_token)
    public_url = ngrok.connect(8000).public_url
    print(f"Uruchomiono publiczny serwer MCP na {public_url}")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    run_mcp_server()