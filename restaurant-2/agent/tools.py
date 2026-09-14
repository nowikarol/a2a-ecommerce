import sqlite3
import asyncio
from data.database import db_file
from network.client import wywolaj_zdalne_narzedzie, URL_HURTOWNI
from data.models import Item, CallForProposal, AcceptProposal, RejectProposal, Proposal
from pydantic import ValidationError
from langchain.tools import tool 

@tool
def sprawdz_magazyn(nazwa_produktu: str) -> str:
    """Sprawdza stan produktu w magazynie bazy danych."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT ilosc, jednostka FROM magazyn WHERE nazwa_produktu COLLATE NOCASE = ?", (nazwa_produktu,))
    wynik = cursor.fetchone()
    conn.close()

    if wynik:
        return f"Mamy na składzie {wynik[0]} {wynik[1]} produktu {nazwa_produktu}."
    return f"Brak produktu {nazwa_produktu} w magazynie."

@tool
def oblicz_braki_dla_dania(nazwa_dania: str, ilosc_porcji: int) -> str:
    """Oblicza brakujące składniki dla wybranego dania i podanej liczby porcji."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM przepisy WHERE nazwa_dania COLLATE NOCASE = ?", (nazwa_dania,))
    przepis = cursor.fetchone()
    if not przepis:
        conn.close()
        return f"Błąd: Nie znaleziono przepisu na '{nazwa_dania}'."

    cursor.execute("SELECT nazwa_produktu, ilosc_wymagana FROM skladniki_przepisow WHERE id_przepisu = ?", (przepis[0],))
    skladniki = cursor.fetchall()

    braki = []
    for nazwa_produktu, ilosc_wymagana in skladniki:
        ilosc_potrzebna = ilosc_wymagana * ilosc_porcji
        cursor.execute("SELECT ilosc FROM magazyn WHERE nazwa_produktu COLLATE NOCASE = ?", (nazwa_produktu,))
        stan_magazynu = cursor.fetchone()
        ilosc_w_magazynie = stan_magazynu[0] if stan_magazynu else 0.0

        if ilosc_potrzebna > ilosc_w_magazynie:
            brakujaca_ilosc = ilosc_potrzebna - ilosc_w_magazynie
            braki.append(f"{brakujaca_ilosc:.2f} kg produktu {nazwa_produktu}")
    conn.close()

    if braki:
        return f"Aby przygotować {ilosc_porcji}x {nazwa_dania}, brakuje: {', '.join(braki)}."
    return f"Mamy składniki na {ilosc_porcji}x {nazwa_dania}. Nie musimy kupować."

@tool
def sprawdz_stan_konta() -> str:
    """Narzędzie do sprawdzania, czy mamy wystarczająco dużo pieniędzy przed zakupem."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT balans FROM konto WHERE id = 1")
    wynik = cursor.fetchone()
    conn.close()
    
    if wynik:
        return f"Aktualny stan konta to: {wynik[0]:.2f} PLN."
    return "Błąd: Nie można odczytać stanu konta."

@tool
def zbierz_oferty_z_hurtowni(produkt: str, ilosc: int) -> str:
    """Wysyła zapytanie ofertowe (CALL_FOR_PROPOSAL) do wszystkich hurtowni i zwraca ich oferty."""
    async def _run():
        raport = f"--- ZEBRAWANE OFERTY DLA {ilosc}x {produkt} ---\n"
        zapytanie = CallForProposal(
            receiver_id="Wszystkie",
            item=Item(name=produkt, quantity=ilosc)
        )
        
        for id_h, url in URL_HURTOWNI.items():
            if not url: continue
            
            zapytanie.receiver_id = id_h
            argumenty = {
                "product_code": produkt,
                "quantity": ilosc,
                "sender_id": "R2",
                "receiver_id": id_h
            }
            
            surowa_odpowiedz = await wywolaj_zdalne_narzedzie(url, "get_proposal", argumenty)
            
            if "Błąd" in surowa_odpowiedz or "REJECT_PROPOSAL" in surowa_odpowiedz:
                raport += f"Hurtownia {id_h}: Odrzuciła zapytanie lub wystąpił błąd.\n"
            else:
                raport += f"Hurtownia {id_h}: Zwróciła wycenę:\n{surowa_odpowiedz}\n"
                
        return raport
    
    return asyncio.run(_run())

@tool
def finalizuj_zakup(wygrana_hurtownia: str, produkt: str, ilosc: int, cena_jednostkowa: float, koszt_calkowity: float) -> str:
    """Akceptuje ofertę zwycięzcy i odrzuca oferty pozostałych hurtowni."""
    async def _run():
        raport = ""
        for id_h, url in URL_HURTOWNI.items():
            if not url: continue
            
            if id_h == wygrana_hurtownia:
                akceptacja = AcceptProposal(
                    receiver_id=id_h,
                    item=Item(name=produkt, quantity=ilosc, price=cena_jednostkowa),
                    total_cost=koszt_calkowity
                )
                # Oczekuje doprecyzowania narzędzia hurtowni do akceptacji
                raport += f"Wysłano ACCEPT_PROPOSAL do {id_h}.\n"
            else:
                odrzucenie = RejectProposal(
                    receiver_id=id_h,
                    item=Item(name=produkt, quantity=ilosc)
                )
                # Oczekuje doprecyzowania narzędzia hurtowni do odrzucenia
                raport += f"Wysłano REJECT_PROPOSAL do {id_h}.\n"
                
        return raport + "Zakończono proces finalizacji."
    
    return asyncio.run(_run())

@tool
def odrzuc_wszystkie_oferty(produkt: str, ilosc: int) -> str:
    """Użyj tego narzędzia, gdy Szef ODRZUCI propozycję zakupu. Wysyła REJECT_PROPOSAL do wszystkich hurtowni."""
    async def _run():
        raport = "Odrzucono oferty z powodu braku zgody Szefa. Wysyłam komunikaty:\n"
        for id_h, url in URL_HURTOWNI.items():
            if not url: continue
            
            argumenty = {
                "sender_id": "R2",
                "receiver_id": id_h,
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": produkt, "quantity": ilosc}
            }
            
            await wywolaj_zdalne_narzedzie(url, "reject_offer", argumenty)
            raport += f"- Wysłano REJECT_PROPOSAL do {id_h}\n"
            
        return raport
    
    return asyncio.run(_run())