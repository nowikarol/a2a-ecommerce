import os
import sys
import uuid
import asyncio
import logging
import aiosqlite
import math
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
from data.database import init_db, db_file
from agent.agent import setup_agent
from contextlib import asynccontextmanager

# Konfiguracja zapisująca logi JEDNOCZEŚNIE do konsoli (dla Orkiestratora) i do pliku (dla GUI)
log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

# Handler do pliku (mode='a' oznacza dopisywanie na końcu pliku)
file_handler = logging.FileHandler('r2_system.log', mode='a', encoding='utf-8')
file_handler.setFormatter(log_formatter)

# Handler do konsoli
stream_handler = logging.StreamHandler(sys.stderr)
stream_handler.setFormatter(log_formatter)

# Główna konfiguracja
logging.basicConfig(
    level=logging.INFO, 
    handlers=[file_handler, stream_handler],
    force=True
    )
logger = logging.getLogger("R2_MAIN")

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("GET /powiadomienia") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

# Słownik przechowujący unikalny identyfikator wątku dla biblioteki LangGraph.
# Pozwala to agentowi pamiętać kontekst rozmowy. Zmiana tego ID powoduje rozpoczęcie pracy z czystą kartą.
stan_sesji = {"watek_id": str(uuid.uuid4())}
agent_lock = asyncio.Lock()
my_agent = None
kolejka_powiadomien = []  # Skrzynka odbiorcza dla GUI

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

async def monitor_magazynu_w_tle(agent):
    """
    Funkcja działająca w nieskończonej pętli, w osobnym wątku. 
    1. Sprawdza, czy brakuje surowców.
    2. Sprawdza, czy można wznowić wstrzymane gotowanie dań (zadania oczekujące).
    """
    ostatnio_zglaszane = set()
    logger.info("Monitor magazynu wystartował w tle (skanuje co 15s).")
    
    while True:
        try:
            await asyncio.sleep(15)

            async with aiosqlite.connect(db_file, timeout=10.0) as conn:
                async with conn.execute(
                    "SELECT nazwa_produktu, ilosc, prog_bezpieczenstwa FROM magazyn WHERE ilosc < prog_bezpieczenstwa"
                ) as cursor:
                    braki_z_bazy = await cursor.fetchall()
        
                # Wyliczenie różnicy zbiorów: szukamy tylko takich braków, których wcześniej nie zgłaszaliśmy.
                obecne_braki = {nazwa for nazwa, _, _ in braki_z_bazy}
                nowe_braki = obecne_braki - ostatnio_zglaszane
                ostatnio_zglaszane = ostatnio_zglaszane.intersection(obecne_braki)

                if nowe_braki:
                    # Tworzymy listę szczegółów braków w formacie "nazwa (ilość kg, próg bezpieczeństwa)"
                    szczegoly_brakow = []
                    for nazwa, ilosc, prog in braki_z_bazy:
                        if nazwa in nowe_braki:
                            do_kupienia = int(math.ceil((prog - ilosc)))
                            szczegoly_brakow.append(f"'{nazwa}' -> ZAMÓW DOKŁADNIE: {do_kupienia:.2f} kg")
                    lista_str = ", ".join(szczegoly_brakow)
                    polecenie_systemowe = (
                        f"SYSTEM: Wykryto krytyczny stan magazynowy! Brakuje: {lista_str}. "
                        f"NIE CZEKAJ na dodatkowe polecenia. Natychmiast użyj narzędzi 'sprawdz_dostepnosc_w_hurtowniach' "
                        f"a potem 'zbierz_oferty_z_hurtowni'. Po zebraniu ofert wyświetl raport i zapytaj o zgodę. "
                        f"NIE używaj znacznika [ZADANIE_ZAKONCZONE]."
                    )

                    async with agent_lock:
                        logger.warning(f"[MONITOR]: Wykryto braki: {lista_str}. Agent analizuje oferty...")
                        config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}  # Utrzymanie tego samego kontekstu pamięci (stan_sesji).
                        # Natywne asynchroniczne wywołanie modelu (ainvoke) ubrane w asyncio.run, by działało bezpiecznie w osobnym wątku monitora.
                        wynik = await agent.ainvoke({"messages": [("user", polecenie_systemowe)]}, config) 
                
                        odpowiedz = przetwarzaj_odpowiedz(wynik['messages'][-1].content)
                
                        # Jeśli Agent uznał zadanie za skończone, czyścimy jego pamięć wygenerowaniem nowego UUID.
                        if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                            odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                            stan_sesji["watek_id"] = str(uuid.uuid4())
                            logger.info("[SYSTEM]: Wątek zresetowany.")
                        logger.info(f"\nAGENT (Raport):\n{odpowiedz}")
                        kolejka_powiadomien.append(odpowiedz)
                    ostatnio_zglaszane.update(nowe_braki)
        
                # Sprawdzenie kolejki
                async with conn.execute(
                    "SELECT id, nazwa_dania, ilosc_porcji FROM zadania_oczekujace WHERE status = 'OCZEKUJE'"
                ) as cursor:
                    zadania = await cursor.fetchall()
        
                for id_zad, nazwa, ilosc in zadania:
                    # Obliczenie, czy w magazynie jest wystarczająco towaru na realizację zaległego przepisu
                    async with conn.execute("""
                        SELECT sp.nazwa_produktu, (sp.ilosc_wymagana * ?) as potrzeba, m.ilosc
                        FROM skladniki_przepisow sp
                        LEFT JOIN magazyn m ON LOWER(sp.nazwa_produktu) = LOWER(m.nazwa_produktu)
                        WHERE sp.id_przepisu = (SELECT id FROM przepisy WHERE nazwa_dania COLLATE NOCASE = ?)
                    """, (ilosc, nazwa)) as ing_cursor:
                        skladniki = await ing_cursor.fetchall() 
                
                    mozna_zrobic = all(stan is not None and float(stan) >= float(potrzeba) for _, potrzeba, stan in skladniki)
            
                    if mozna_zrobic:
                        await conn.execute("UPDATE zadania_oczekujace SET status = 'W_TRAKCIE' WHERE id = ?", (id_zad,))
                        await conn.commit()
                
                        polecenie_kuchenne = (
                            f"SYSTEM: Dobra wiadomość! Dotarła dostawa. Składniki na oczekujące zamówienie "
                            f"({ilosc}x '{nazwa}') są już dostępne w magazynie. "
                            f"Użyj NATYCHMIAST narzędzia 'przygotuj_danie' aby je ugotować. Gdy skończysz, dodaj [ZADANIE_ZAKONCZONE]."
                        )
                
                        async with agent_lock:
                            logger.info(f"[MONITOR]: Dostawa dotarła. Agent wznawia gotowanie: {nazwa}")
                            config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
                            wynik = await agent.ainvoke({"messages": [("user", polecenie_kuchenne)]}, config)
                    
                            odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
                            if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                                odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                                stan_sesji["watek_id"] = str(uuid.uuid4())
                                logger.info("Gotowanie zakończone. Wątek zresetowany.")
                                kolejka_powiadomien.append(odpowiedz)
                        
                            logger.info(f"RAPORT AGENTA:\n{odpowiedz}")
                    
        except asyncio.CancelledError:
            logger.info("Monitor magazynu został zatrzymany.")
            break
        except Exception as e:
            logger.error(f"[MONITOR BŁĄD]: {e}", exc_info=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global my_agent
    load_dotenv()
    init_db()
    my_agent = setup_agent()
    
    # Uruchomienie pętli w tle jako zadania w tej samej pętli asynchronicznej
    task = asyncio.create_task(monitor_magazynu_w_tle(my_agent))
    logger.info("API Agenta gotowe na port 8022. Oczekuję na komendy Orkiestratora...")
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Restauracja 2 - Agent API", lifespan=lifespan)

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Natywnie asynchroniczny endpoint FastAPI."""
    if not req.polecenie.strip():
        return ChatResponse(odpowiedz="", watek_zresetowany=False)
     
    if agent_lock.locked():
        return ChatResponse(
            odpowiedz="⚠️ **SYSTEM:** Agent jest w tej chwili zajęty innym zadaniem (analizuje rynek w tle). Poczekaj na jego raport i spróbuj ponownie póżniej.", 
            watek_zresetowany=False
        )
    logger.info(f"SZEF (Orkiestrator): {req.polecenie}")
    
    async with agent_lock:
        config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
        wynik = await my_agent.ainvoke({"messages": [("user", req.polecenie)]}, config)
        
        odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
        zresetowano = False
        
        if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
            odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
            stan_sesji["watek_id"] = str(uuid.uuid4())
            logger.info("[SYSTEM]: Zadanie zakończone. Wątek zresetowany.")
            zresetowano = True
            
        logger.info(f"AGENT:\n{odpowiedz}")
        return ChatResponse(odpowiedz=odpowiedz, watek_zresetowany=zresetowano)

@app.get("/powiadomienia")
async def pobierz_powiadomienia():
    """Endpoint dla GUI, aby mogło odebrać wiadomości wygenerowane w tle przez Monitor."""
    global kolejka_powiadomien
    kopia = kolejka_powiadomien.copy()
    kolejka_powiadomien.clear() # Czyścimy skrzynkę po odebraniu
    return {"nowe_wiadomosci": kopia}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8022)