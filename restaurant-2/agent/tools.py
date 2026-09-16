import sqlite3
import asyncio
from data.database import db_file
from network.client import wywolaj_zdalne_narzedzie, URL_HURTOWNI
from data.models import Item, CallForProposal, AcceptProposal, RejectProposal, Proposal, AvailabilityRequest
from pydantic import ValidationError
from langchain.tools import tool 
import json

@tool
def sprawdz_magazyn(nazwa_produktu: str) -> str:
    """Sprawdza stan produktu w magazynie bazy danych."""
    conn = sqlite3.connect(db_file, timeout=10.0) # Płączenie się z bazą danych
    cursor = conn.cursor() # Kursor to obiekt służący do wykonywania komend SQL.
    cursor.execute("SELECT ilosc, jednostka FROM magazyn WHERE nazwa_produktu COLLATE NOCASE = ?", (nazwa_produktu,))
    wynik = cursor.fetchone() #Pobiera pierwszy pasujący wiersz z wyników zapytania.
    conn.close() # Zamykamy połączenie z bazą danych, aby nie blokować innych operacji

    if wynik:
        return f"Mamy na składzie {wynik[0]} {wynik[1]} produktu {nazwa_produktu}."
    return f"Brak produktu {nazwa_produktu} w magazynie."

@tool
def sprawdz_stan_konta() -> str:
    """Narzędzie do sprawdzania, czy mamy wystarczająco dużo pieniędzy przed zakupem."""
    conn = sqlite3.connect(db_file, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT balans FROM konto WHERE id = 1")
    wynik = cursor.fetchone()
    conn.close()
    
    if wynik:
        return f"Aktualny stan konta to: {wynik[0]:.2f} PLN."
    return "Błąd: Nie można odczytać stanu konta."

@tool
async def sprawdz_dostepnosc_w_hurtowniach(produkt: str, ilosc: int) -> str:
    """Sprawdza, czy hurtownie posiadają na stanie wymaganą ilość produktu przed zapytaniem o cenę."""
    raport = f"STATUS DOSTĘPNOŚCI: {ilosc}x {produkt} ---\n"
    dostepne_hurtownie = [] 

    # Iteracja po słowniku hurtowni (np. H1, H2) i ich adresach.
    for id_h, url in URL_HURTOWNI.items():
        if not url: continue

        # Użycie modelu Pydantic do zbudowania poprawnego JSON-a zgodnego ze schematem.
        request = AvailabilityRequest(
            receiver_id=id_h,
            item=Item(name=produkt, quantity=ilosc)
        )
        argumenty = request.model_dump() # Zmiana obiektu Python na słownik

        # Wywołanie asynchronicznej funkcji sieciowej zdefiniowanej w client.py. 
        # Przekazujemy tu intencję, z której skorzysta LLM Router w razie braku domyślnego narzędzia.
        surowa_odpowiedz = await wywolaj_zdalne_narzedzie(
            url=url, 
            domyslna_nazwa="check_availability", 
            intencja="Sprawdzenie dostępności surowca i stanu magazynowego hurtowni",
            argumenty=argumenty
        )

        if str(surowa_odpowiedz).startswith("Błąd sieciowy"):
            raport += f"Hurtownia {id_h}: SERWER WYŁĄCZONY (Brak połączenia).\n"
            continue

        try:
            # Próba odczytania tekstowej odpowiedzi serwera jako struktury JSON.
            odpowiedz_json = json.loads(surowa_odpowiedz)
            if odpowiedz_json.get("is_available") is True:
                raport += f"Hurtownia {id_h}: Posiada towar.\n"
                dostepne_hurtownie.append(id_h) # Zapisujemy hurtownię jako "dostępną" na później
            else:
                raport += f"Hurtownia {id_h}: Brak towaru w tej ilości.\n"
        except json.JSONDecodeError:
            raport += f"Hurtownia {id_h}: Błąd komunikacji (niezgodność z JSON).\n"

    if not dostepne_hurtownie:
        raport += "\nUWAGA: Żadna hurtownia nie ma tego towaru na stanie! Przerwij proces zakupowy."
    else:
        raport += f"\nDostępne w: {', '.join(dostepne_hurtownie)}. Możesz bezpiecznie zebrać od nich oferty cenowe."

    return raport

@tool
def oblicz_braki_dla_dania(nazwa_dania: str, ilosc_porcji: int) -> str:
    """Oblicza brakujące składniki dla wybranego dania i podanej liczby porcji."""
    conn = sqlite3.connect(db_file, timeout=10.0)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM przepisy WHERE nazwa_dania COLLATE NOCASE = ?", (nazwa_dania,))
    przepis = cursor.fetchone()
    if not przepis:
        conn.close()
        return f"Błąd: Nie znaleziono przepisu na '{nazwa_dania}'."

    cursor.execute("SELECT nazwa_produktu, ilosc_wymagana FROM skladniki_przepisow WHERE id_przepisu = ?", (przepis[0],))
    skladniki = cursor.fetchall() # Pobieramy wszystkie składniki przepisu z tabeli 'skladniki_przepisow' dla danego przepisu.

    braki = [] # Lista brakujących składników, które zostaną zwrócone w raporcie.
    # Sprawdzamy każdy składnik przepisu po kolei
    for nazwa_produktu, ilosc_wymagana in skladniki:
        ilosc_potrzebna = ilosc_wymagana * ilosc_porcji # Obliczamy, ile tego składnika potrzebujemy dla podanej liczby porcji

        # Sprawdzamy, ile tego składnika leży obecnie w magazynie
        cursor.execute("SELECT ilosc FROM magazyn WHERE nazwa_produktu COLLATE NOCASE = ?", (nazwa_produktu,))
        stan_magazynu = cursor.fetchone()
        ilosc_w_magazynie = stan_magazynu[0] if stan_magazynu else 0.0 # Jeśli nie ma towaru w tabeli, przyjmujemy, że stan = 0.0

        # Wyliczamy deficyt
        if ilosc_potrzebna > ilosc_w_magazynie:
            brakujaca_ilosc = ilosc_potrzebna - ilosc_w_magazynie
            braki.append(f"{brakujaca_ilosc:.2f} kg produktu {nazwa_produktu}")
    conn.close()

    if braki:
        return f"Aby przygotować {ilosc_porcji}x {nazwa_dania}, brakuje: {', '.join(braki)}."
    return f"Mamy składniki na {ilosc_porcji}x {nazwa_dania}. Nie musimy kupować."

@tool
async def zbierz_oferty_z_hurtowni(produkt: str, ilosc: int, dostepne_hurtownie: list[str]) -> str:
    """Wysyła zapytanie ofertowe (CALL_FOR_PROPOSAL) TYLKO do wskazanych hurtowni."""
    raport = f"--- ZEBRANE OFERTY DLA {ilosc}x {produkt} ---\n"
    
    for id_h, url in URL_HURTOWNI.items():
        # Zabezpieczenie: wysyłamy zapytanie o cenę tylko do tych, co zgłosili dostępność towaru
        if id_h not in dostepne_hurtownie: 
            continue
        if not url: continue

        proposal = CallForProposal(
            receiver_id=id_h,
            item=Item(name=produkt, quantity=ilosc)
        )
        argumenty = proposal.model_dump()
       
        surowa_odpowiedz = await wywolaj_zdalne_narzedzie(
            url=url, 
            domyslna_nazwa="request_offer", 
            intencja="Złożenie zapytania ofertowego (CALL FOR PROPOSAL) i pobranie wyceny towaru",
            argumenty=argumenty
        )
        
        if "Błąd" in surowa_odpowiedz or "REJECT_PROPOSAL" in surowa_odpowiedz:
            raport += f"Hurtownia {id_h}: Odrzuciła zapytanie lub wystąpił błąd.\n"
        else:
            raport += f"Hurtownia {id_h}: Zwróciła wycenę:\n{surowa_odpowiedz}\n"
            
    return raport

@tool
async def finalizuj_zakup(wygrana_hurtownia: str, produkt: str, ilosc: int, cena_jednostkowa: float, koszt_calkowity: float) -> str:
    """
    Wysyła komunikat ACCEPT_PROPOSAL do wybranej hurtowni w celu sfinalizowania transakcji.
    Zgodnie z zasadą milczenia protokołu CNP, NIE wysyła powiadomień do hurtowni przegranych.
    Zwraca odpowiedź od hurtowni - jeśli hurtownia potwierdzi, zamówienie jest w drodze.
    Jeśli hurtownia odrzuci (błąd Race Condition - towar wyprzedany w międzyczasie), 
    narzędzie zwróci informację o odrzuceniu (REJECT_PROPOSAL).
    """
    url = URL_HURTOWNI.get(wygrana_hurtownia)
    if not url: 
        return f"Błąd: Nie znaleziono adresu dla {wygrana_hurtownia}."

    accept = AcceptProposal(
        receiver_id=wygrana_hurtownia,
        item=Item(name=produkt, quantity=ilosc, price=cena_jednostkowa),
        total_cost=koszt_calkowity
    )
    argumenty = accept.model_dump()
    
    surowa_odpowiedz = await wywolaj_zdalne_narzedzie(
        url=url, 
        domyslna_nazwa="accept_offer", 
        intencja="Akceptacja oferty cenowej (ACCEPT PROPOSAL), złożenie i potwierdzenie zamówienia",
        argumenty=argumenty
    )
    
    return f"Odpowiedź z hurtowni {wygrana_hurtownia} po finalizacji:\n{surowa_odpowiedz}"

@tool
def wplac_srodki(kwota: float, opis: str = "Wpłata własna") -> str:
    """Wpłaca środki pieniężne (PLN) na konto restauracji i rejestruje wpłatę w historii."""
    if kwota <= 0:
        return "Błąd: Kwota wpłaty musi być większa od zera."

    conn = sqlite3.connect(db_file, timeout=20.0)
    try:
        # Blok "with conn:" uruchamia bezpieczną transakcję (ACID). Jeśli jakakolwiek funkcja execute() w tym bloku zwróci błąd, cała transakcja
        # jest natychmiast anulowana (rollback), a zmiany nie zostaną zapisane w bazie.
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE konto SET balans = balans + ? WHERE id = 1", (kwota,))
            cursor.execute(
                "INSERT INTO historia_transakcji (typ_akcji, od_kogo, produkt, ilosc, koszt) VALUES (?, ?, ?, ?, ?)",
                (f"WPŁATA ({opis})", "SZEF", "PLN", 1, kwota),
            )
        
        cursor = conn.cursor()
        cursor.execute("SELECT balans FROM konto WHERE id = 1")
        nowy_balans = cursor.fetchone()[0]
        return f"Wpłacono {kwota:.2f} PLN. Aktualny stan konta: {nowy_balans:.2f} PLN."
    finally:
        conn.close() # Blok finally wykonuje się zawsze (nawet przy błędzie). Zapewnia to zamknięcie bazy.

@tool
def przygotuj_danie(nazwa_dania: str, ilosc_porcji: int = 1) -> str:
    """
    Przygotowuje danie w kuchni i odejmuje składniki ze spiżarni.
    Jeśli brakuje składników, nie modyfikuje magazynu i raportuje deficyt do zaopatrzenia oraz dodaje zadanie do kolejki oczekujących.
    """
    if ilosc_porcji <= 0:
        return "Błąd: Liczba porcji musi być > 0."

    conn = sqlite3.connect(db_file, timeout=10.0)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM przepisy WHERE nazwa_dania COLLATE NOCASE = ?", (nazwa_dania,))
    przepis = cursor.fetchone()
    if not przepis:
        conn.close()
        return f"Błąd: Nie znaleziono przepisu na '{nazwa_dania}'."

    cursor.execute(
        "SELECT nazwa_produktu, ilosc_wymagana FROM skladniki_przepisow WHERE id_przepisu = ?",
        (przepis[0],)
    )
    skladniki = cursor.fetchall()

    braki = [] # Lista brakujących składników, które zostaną zwrócone w raporcie.
    zapotrzebowanie = [] # Lista składników i ich potrzebnej ilości, które zostaną odjęte od magazynu, jeśli wszystko jest dostępne.

    for nazwa_produktu, ilosc_wymagana in skladniki:
        potrzebna_ilosc = ilosc_wymagana * ilosc_porcji
        cursor.execute("SELECT ilosc FROM magazyn WHERE nazwa_produktu COLLATE NOCASE = ?", (nazwa_produktu,))
        stan = cursor.fetchone()
        aktualna_ilosc = stan[0] if stan else 0.0

        if potrzebna_ilosc > aktualna_ilosc:
            braki.append(f"{potrzebna_ilosc - aktualna_ilosc:.2f} kg {nazwa_produktu}") # Dodajemy do listy braków
        zapotrzebowanie.append((nazwa_produktu, potrzebna_ilosc)) # Dodajemy do listy zapotrzebowania, aby później odjąć od magazynu

    # ŚCIEŻKA A: BRAK SKŁADNIKÓW
    if braki:
        try:
            with conn:
                # Blokujemy przygotowanie posiłku, ale zapisujemy to żądanie do kolejki.
                # 'Monitor w tle' znajdzie ten zapis i wznowi gotowanie po najbliższej dostawie.
                cursor.execute(
                    "INSERT INTO zadania_oczekujace (nazwa_dania, ilosc_porcji, status) VALUES (?, ?, 'OCZEKUJE')",
                    (nazwa_dania, ilosc_porcji)
                )
        finally:
            conn.close()
        return (
            f"Brak surowców: {', '.join(braki)}. "
            f"Zadanie ugotowania zostało wstrzymane i dodane do kolejki oczekujących. "
            f"Rozpocznij procedurę zbierania ofert na te braki."
        )
    # ŚCIEŻKA B: SUKCES
    try:
        with conn:
            # Odejmujemy wymagane surowce ze stanu magazynowego
            for nazwa_produktu, potrzebna_ilosc in zapotrzebowanie:
                cursor.execute(
                    "UPDATE magazyn SET ilosc = ilosc - ? WHERE nazwa_produktu COLLATE NOCASE = ?",
                    (potrzebna_ilosc, nazwa_produktu)
                )
            # Jeśli to zadanie wcześniej było w kolejce oczekujących, to zdejmujemy z niego ten status, oznaczając jako zrealizowane.
            cursor.execute(
                "UPDATE zadania_oczekujace SET status = 'ZAKONCZONE' WHERE nazwa_dania COLLATE NOCASE = ? AND status IN ('OCZEKUJE', 'W_TRAKCIE')",
                (nazwa_dania,)
            )
    finally:
        conn.close()

    return f"SUKCES: Wydano z kuchni {ilosc_porcji}x '{nazwa_dania}'. Stany magazynowe zaktualizowane."