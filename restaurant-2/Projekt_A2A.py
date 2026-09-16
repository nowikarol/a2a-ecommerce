import threading
import uuid
import time
import sqlite3
import asyncio
from dotenv import load_dotenv
from data.database import init_db, db_file
from agent.agent import setup_agent

# Słownik przechowujący unikalny identyfikator wątku dla biblioteki LangGraph.
# Pozwala to agentowi pamiętać kontekst rozmowy. Zmiana tego ID powoduje rozpoczęcie pracy z czystą kartą.
stan_sesji = {"watek_id": str(uuid.uuid4())}

# Blokada dla konsoli. Zapobiega sytuacji, w której Monitor w tle i Główny Czat próbują jednocześnie pisać na ekran.
konsola_lock = threading.Lock() 

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
    ostatnio_zglaszane = set() # Zbiór pamiętający ostatnio zgłoszone braki, żeby Monitor nie spamował co 15 sekund tym samym komunikatem o braku pomidorów.
    
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

            # with konsola_lock - przejmujemy wyłączną kontrolę nad terminalem
            with konsola_lock:
                print("[MONITOR]: Wykryto braki! Agent analizuje oferty...")
                config = {"configurable": {"thread_id": stan_sesji["watek_id"]}} # Utrzymanie tego samego kontekstu pamięci (stan_sesji).
                # Natywne asynchroniczne wywołanie modelu (ainvoke) ubrane w asyncio.run, by działało bezpiecznie w osobnym wątku monitora.
                wynik = asyncio.run(agent.ainvoke({"messages": [("user", polecenie_systemowe)]}, config)) 
                
                odpowiedz = przetwarzaj_odpowiedz(wynik['messages'][-1].content)
                
                # Jeśli Agent uznał zadanie za skończone, czyścimy jego pamięć wygenerowaniem nowego UUID.
                if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                    odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                    print(f"\nAGENT (Raport):\n{odpowiedz}")
                    stan_sesji["watek_id"] = str(uuid.uuid4())
                    print("[SYSTEM]: Wątek zresetowany.")
                else:
                    print(f"\nAGENT (Raport):\n{odpowiedz}")
                
                print("\nSZEF: ", end="", flush=True)
            ostatnio_zglaszane.update(nowe_braki) # Dodajemy nowe braki do pamięci, by ich nie duplikować
        
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
                
                with konsola_lock:
                    print(f"[MONITOR]: Dostawa dotarła. Agent wznawia gotowanie: {nazwa}")
                    config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
                    wynik = asyncio.run(agent.ainvoke({"messages": [("user", polecenie_kuchenne)]}, config))
                    
                    odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
                    if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                        odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                        print(f"\nAGENT:\n{odpowiedz}")
                        stan_sesji["watek_id"] = str(uuid.uuid4())
                        print("[SYSTEM]: Wątek zresetowany.")
                    else:
                        print(f"\nAGENT:\n{odpowiedz}")
                    
                    print("\nSZEF: ", end="", flush=True)
                    
        conn.close()

def chat_loop(agent):
    with konsola_lock:
        print("SYSTEM ZAOPATRZENIA (AGENT) URUCHOMIONY")
        print("Monitor magazynu działa w tle (skanuje co 15 sekund).")
        print("Wpisz 'wyjscie', aby zamknąć program.")

    while True:
        polecenie = input("\nSZEF: ")
        
        if polecenie.strip().lower() in ['koniec', 'wyjscie', 'exit', 'quit']:
            with konsola_lock:
                print("AGENT: Do widzenia, Szefie! Czat wyłączony.")
            break
            
        # Zignorowanie pustych "enterów
        if not polecenie.strip():
            continue

        # Po wpisaniu komendy, blokujemy konsolę, wysyłamy zapytanie do LLM i czekamy na odp.
        with konsola_lock:
            print("AGENT: (Myślę...)")
            config = {"configurable": {"thread_id": stan_sesji["watek_id"]}}
            wynik = asyncio.run(agent.ainvoke({"messages": [("user", polecenie)]}, config))
        
            odpowiedz = przetwarzaj_odpowiedz(wynik["messages"][-1].content)
            
            if "[ZADANIE_ZAKONCZONE]" in odpowiedz:
                odpowiedz = odpowiedz.replace("[ZADANIE_ZAKONCZONE]", "").strip()
                print(f"\nAGENT:\n{odpowiedz}")
                
                stan_sesji["watek_id"] = str(uuid.uuid4())
                print(f"[SYSTEM]: Zadanie zakończone.")
            else:
                print(f"\nAGENT:\n{odpowiedz}")

if __name__ == "__main__":
    load_dotenv()
    init_db()

    my_agent = setup_agent()  # Inicjalizacja LLM
    
    # Uruchomienie Monitora jako wątku 'daemon'. Oznacza to, że gdy wyłączy się główny program, ten wątek również automatycznie zginie i nie będzie działał w nieskończoność w tle (zombi).
    threading.Thread(target=monitor_magazynu_w_tle, args=(my_agent,), daemon=True).start()

    chat_loop(my_agent) # Odpalenie głównego komunikatora