import os
import sys
import uuid
import time
import sqlite3
import asyncio
import threading
import logging
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
from data.database import init_db, db_file
from agent.agent import setup_agent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("R2_MAIN")

# Słownik przechowujący unikalny identyfikator wątku dla biblioteki LangGraph.
# Pozwala to agentowi pamiętać kontekst rozmowy. Zmiana tego ID powoduje rozpoczęcie pracy z czystą kartą.
stan_sesji = {"watek_id": str(uuid.uuid4())}
agent_lock = threading.Lock()

app = FastAPI(title="Restauracja 2 - Agent API")
my_agent = None

class ChatRequest(BaseModel):
    polecenie: str

class ChatResponse(BaseModel):
    odpowiedz: str
    watek_zresetowany: bool

def przetwarzaj_odpowiedz(zawartosc_odpowiedzi: str | list) -> str:
    """Oczyszcza odpowiedź ze znaczników bezpieczeństwa."""
    if isinstance(zawartosc_odpowiedzi, list): # Jeśli odpowiedź jest listą bloków, łączymy tylko te, które mają klucz "text"
        return "\n".join([blok["text"] for blok in zawartosc_odpowiedzi if isinstance(blok, dict) and "text" in blok])
    return zawartosc_odpowiedzi

def monitor_magazynu_w_tle(agent):
    """
    Funkcja działająca w nieskończonej pętli, w osobnym wątku. 
    1. Sprawdza, czy brakuje surowców.
    2. Sprawdza, czy można wznowić wstrzymane gotowanie dań (zadania oczekujące).
    """
    ostatnio_zglaszane = set()
    logger.info("Monitor magazynu wystartował w tle (skanuje co 15s).")
    
    while True:
        time.sleep(15)

        conn = sqlite3.connect(db_file, timeout=10.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT nazwa_produktu, ilosc, prog_bezpieczenstwa FROM magazyn WHERE ilosc <= prog_bezpieczenstwa")
        braki_z_bazy = cursor.fetchall()
        
        # Wyliczenie różnicy zbiorów: szukamy tylko takich braków, których wcześniej nie zgłaszaliśmy.
        obecne_braki = {nazwa for nazwa, _, _ in braki_z_bazy}
        nowe_braki = obecne_braki - ostatnio_zglaszane
        ostatnio_zglaszane = ostatnio_zglaszane.intersection(obecne_braki)

        if nowe_braki:
            # Tworzymy listę szczegółów braków w formacie "nazwa (ilość kg, próg bezpieczeństwa)"
            szczegoly_brakow = [f"{nazwa} ({ilosc} kg, próg {prog})" for nazwa, ilosc, prog in braki_z_bazy if nazwa in nowe_braki]
            lista_str = ", ".join(szczegoly_brakow)
            polecenie_systemowe = (
                f"SYSTEM: Wykryto krytyczny stan magazynowy! Brakuje: {lista_str}. "
                f"NIE CZEKAJ na dodatkowe polecenia. Natychmiast użyj narzędzi 'sprawdz_dostepnosc_w_hurtowniach' "
                f"a potem 'zbierz_oferty_z_hurtowni'. Po zebraniu ofert wyświetl raport i zapytaj o zgodę. "
                f"NIE używaj znacznika [ZADANIE_ZAKONCZONE]."
            )

            with agent_lock:
                logger.warning(f"[MONITOR]: Wykryto braki: {lista_str}. Agent analizuje oferty...")
                config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}  # Utrzymanie tego samego kontekstu pamięci (stan_sesji).
                # Natywne asynchroniczne wywołanie modelu (ainvoke) ubrane w asyncio.run, by działało bezpiecznie w osobnym wątku monitora.
                wynik = asyncio.run(agent.ainvoke({"messages": [("user", polecenie_systemowe)]}, config)) 
                
                odpowiedz = przetwarzaj_odpowiedz(wynik['messages'][-1].content)
                
                # Jeśli Agent uznał zadanie za skończone, czyścimy jego pamięć wygenerowaniem nowego UUID.
                if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                    odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                    stan_sesji["watek_id"] = str(uuid.uuid4())
                    logger.info("[SYSTEM]: Wątek zresetowany.")
                logger.info(f"\nAGENT (Raport):\n{odpowiedz}")
            ostatnio_zglaszane.update(nowe_braki)
        
        # Sprawdzenie kolejki
        cursor.execute("SELECT id, nazwa_dania, ilosc_porcji FROM zadania_oczekujace WHERE status = 'OCZEKUJE'")
        zadania = cursor.fetchall()
        
        for id_zad, nazwa, ilosc in zadania:
            # Obliczenie, czy w magazynie jest wystarczająco towaru na realizację zaległego przepisu
            cursor.execute("""
                SELECT sp.nazwa_produktu, (sp.ilosc_wymagana * ?) as potrzeba, m.ilosc
                FROM skladniki_przepisow sp
                LEFT JOIN magazyn m ON LOWER(sp.nazwa_produktu) = LOWER(m.nazwa_produktu)
                WHERE sp.id_przepisu = (SELECT id FROM przepisy WHERE nazwa_dania COLLATE NOCASE = ?)
            """, (ilosc, nazwa))
            skladniki = cursor.fetchall() 
            
            mozna_zrobic = all(stan is not None and float(stan) >= float(potrzeba) for _, potrzeba, stan in skladniki)
            
            if mozna_zrobic:
                with conn:
                    cursor.execute("UPDATE zadania_oczekujace SET status = 'W_TRAKCIE' WHERE id = ?", (id_zad,))
                
                polecenie_kuchenne = (
                    f"SYSTEM: Dobra wiadomość! Dotarła dostawa. Składniki na oczekujące zamówienie "
                    f"({ilosc}x '{nazwa}') są już dostępne w magazynie. "
                    f"Użyj NATYCHMIAST narzędzia 'przygotuj_danie' aby je ugotować. Gdy skończysz, dodaj [ZADANIE_ZAKONCZONE]."
                )
                
                with agent_lock:
                    logger.info(f"[MONITOR]: Dostawa dotarła. Agent wznawia gotowanie: {nazwa}")
                    config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
                    wynik = asyncio.run(agent.ainvoke({"messages": [("user", polecenie_kuchenne)]}, config))
                    
                    odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
                    if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                        odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                        stan_sesji["watek_id"] = str(uuid.uuid4())
                        logger.info("Gotowanie zakończone. Wątek zresetowany.")
                        
                    logger.info(f"RAPORT AGENTA:\n{odpowiedz}")
                    
        conn.close()

@app.on_event("startup")
def startup_event():
    global my_agent
    load_dotenv()
    init_db()
    my_agent = setup_agent()
    threading.Thread(target=monitor_magazynu_w_tle, args=(my_agent,), daemon=True).start()
    logger.info("API Agenta gotowe na port 8022. Oczekuję na komendy Orkiestratora...")

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    """Endpoint dla Orkiestratora zastępujący systemowy input()"""
    if not req.polecenie.strip():
        return ChatResponse(odpowiedz="", watek_zresetowany=False)
        
    logger.info(f"SZEF (Orkiestrator): {req.polecenie}")
    
    with agent_lock:
        config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
        wynik = asyncio.run(my_agent.ainvoke({"messages": [("user", req.polecenie)]}, config))
        
        odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
        zresetowano = False
        
        if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
            odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
            stan_sesji["watek_id"] = str(uuid.uuid4())
            logger.info("[SYSTEM]: Zadanie zakończone. Wątek zresetowany.")
            zresetowano = True
            
        logger.info(f"AGENT:\n{odpowiedz}")
        return ChatResponse(odpowiedz=odpowiedz, watek_zresetowany=zresetowano)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8022)