# 🍕 Restauracja nr 2 (`R2`) - Autonomiczny Agent Zaopatrzeniowy (MAS)

Nowoczesny, w pełni asynchroniczny węzeł handlowy Restauracji nr 2, działający w architekturze wieloagentowego łańcucha dostaw (Multi-Agent System). Aplikacja jest zasilana przez model Google Gemini 3.1 Flash-Lite (za pośrednictwem LangChain), integruje komunikację sieciową za pomocą Model Context Protocol (FastMCP) i rygorystycznie przestrzega standardu Contract Net Protocol (CNP) w procesach zakupowych.
Projekt składa się z serwera nasłuchującego na dostawy, REST API z orkiestratorem (FastAPI), interfejsu graficznego dla użytkownika (Streamlit) oraz monitora działającego w tle.

---

## 📋 Spis Treści
- [Główne Funkcjonalności](#główne-funkcjonalności)
- [Struktura Projektu](#struktura-projektu)
- [Narzędzia Agenta i Serwera (Tools)](#narzędzia-agenta-i-serwera-tools)
- [Protokół CNP (5 Kroków)](#protokół-cnp-5-kroków)
- [Konfiguracja Środowiska (.env)](#konfiguracja-środowiska-env)
- [Uruchomienie Systemu](#uruchomienie-systemu)

---

## ✨ Główne Funkcjonalności
* 🗄️ **Relacyjna baza danych SQL (`data/restauracja_2.db`):** Zarządza magazynem surowców (w tym progami bezpieczeństwa), portfelem finansowym (w PLN), recepturami, historią transakcji oraz kolejką zamówień kuchennych. Działa w trybie WAL (Write-Ahead Logging) dla obsługi współbieżności.
* 🤖 **Proaktywny Agent AI:** Działa w oparciu o precyzyjny prompt systemowy. Agent podejmuje decyzje biznesowe, rezerwuje budżet, ale nigdy samodzielnie nie wydaje pieniędzy bez autoryzacji "Szefa" (zasada Human-in-the-Loop).
* 🔄 **Monitor Magazynu (Background Task):** Niezależny proces działający w tle skanuje bazę co 15 sekund. W przypadku wykrycia braków magazynowych (poniżej progu bezpieczeństwa), automatycznie inicjuje proces poszukiwania ofert u hurtowników. Oczekujące zamówienia kuchenne są samoczynnie wznawiane po zaksięgowaniu dostawy.
* 🧠 **Dynamiczny Router Narzędzi LLM:** Jeśli zewnętrzna hurtownia zmieni nazwę swoich narzędzi MCP, wbudowany agent-router (w `client.py`) dynamicznie dopasuje intencję akcji do dostępnych u dostawcy narzędzi na podstawie ich opisów.
* 📊 **Panel Dowodzenia (Streamlit GUI):** Interaktywny interfejs pozwalający na komunikację z Agentem na czacie, podgląd stanu magazynu w czasie rzeczywistym, weryfikację budżetu oraz odbiór powiadomień z procesów działających w tle.
* 🛡️ **Ochrona przed Race Condition:** System obsługuje scenariusze, w których zwycięska hurtownia wyprzeda towar w trakcie trwania negocjacji. Agent automatycznie proponuje wtedy drugą najtańszą ofertę (Fallback).

---

## 📁 Struktura Projektu

Projekt zachowuje ścisłą separację warstw (Separation of Concerns):
```text
Restauracja_2/
├── data/                       # WARSTWA DANYCH (Baza i Walidacja)
│   ├── models.py               # Modele Pydantic (CNP: CallForProposal, AcceptProposal, Delivery)
│   ├── database.py             # Logika SQLite, konfiguracja trybu WAL dla współbieżności
│   └── baza_r2_projektA2A.sql  # Schemat DDL SQL i dane startowe (seed)
│
├── agent/                      # WARSTWA INTELIGENCJI
│   ├── agent.py                # Konfiguracja LangChain, pamięć LangGraph, Prompt Systemowy
│   └── tools.py                # Narzędzia Agenta (dostęp do SQL i wywoływanie sieci)
│
├── network/                    # WARSTWA KOMUNIKACJI (MCP)
│   ├── server.py               # Publiczny Serwer FastMCP (odbieranie towaru - `receive_delivery`)
│   └── client.py               # Asynchroniczny Klient SSE MCP z systemem Fallback/LLM Router
│
├── Projekt_A2A.py              # Główny silnik (FastAPI, Monitor w tle, Endpointy czatu)
├── gui.py                      # Aplikacja frontendowa (Streamlit Dashboard)
└── .env                        # Zmienne środowiskowe (klucze API, porty, URL-e hurtowni)
```

---

## 🛠️ Narzędzia Agenta i Serwera (Tools)

System wykorzystuje ściśle odseparowane narzędzia do zarządzania wewnętrzną logiką oraz komunikacji ze światem zewnętrznym.

### 🤖 Narzędzia Agenta (Wykonywane Lokalnie)
Narzędzia przypisane do Agenta LLM, pozwalające mu odczytywać dane i modyfikować procesy wewnętrzne:

1. **`sprawdz_magazyn(nazwa_produktu)`**
   Sprawdza fizyczny stan konkretnego produktu (ilość i jednostkę) w bazie SQLite.
2. **`sprawdz_stan_konta()`**
   Zwraca aktualny balans konta restauracji w PLN, niezbędny do sprawdzenia, czy budżet pozwala na opłacenie zebranych ofert.
3. **`sprawdz_dostepnosc_w_hurtowniach(produkt, ilosc)`**
   Asynchronicznie, w sposób zrównoleglony odpytuje zdefiniowane w systemie hurtownie (wysyła model `AvailabilityRequest`), czy posiadają na stanie zadaną ilość towaru. Nie pyta o cenę.
4. **`oblicz_braki_dla_dania(nazwa_dania, ilosc_porcji)`**
   Rozbija danie na poszczególne składniki bazując na tabeli przepisów. Weryfikuje wymaganą ilość z aktualnym stanem magazynu i zwraca precyzyjną listę braków.
5. **`zbierz_oferty_z_hurtowni(produkt, ilosc, dostepne_hurtownie)`**
   Kieruje zapytania ofertowe (`CallForProposal`) równolegle *wyłącznie* do hurtowni wyselekcjonowanych w poprzednim etapie. Zwraca raport z wycenami.
6. **`finalizuj_zakup(wygrana_hurtownia, produkt, ilosc, cena_jednostkowa, koszt_calkowity)`**
   Wysyła komunikat `AcceptProposal` do zwycięzcy przetargu. Narzędzie obsługuje błędy typu "Race Condition" – potrafi przechwycić informację z hurtowni o tym, że towar został wyprzedany w międzyczasie. Zgodnie z zasadą milczenia protokołu CNP, nie powiadamia przegranych hurtowni.
7. **`wplac_srodki(kwota, opis)`**
   Pozwala Agentowi obsłużyć sytuację, w której Szef decyduje się na zewnętrzne zasilenie (dokapitalizowanie) konta restauracji.
8. **`przygotuj_danie(nazwa_dania, ilosc_porcji)`**
   Fizycznie realizuje zamówienie w kuchni poprzez odjęcie składników z magazynu. Jeśli surowców brakuje, dodaje wpis do tabeli `zadania_oczekujace` (skąd zostanie wzniesione przez Monitor zaraz po przyszłej dostawie).

### 🌐 Narzędzia Serwera (Publiczne FastMCP)
Udostępniane "na zewnątrz" dla hurtowni.

1. **`receive_delivery(delivery_data)`**
   Zdalne narzędzie wystawione na serwerze (port 8003). Odbiera wygenerowany przez hurtownię dokument dostawy (`Delivery`). Waliduje go za pomocą Pydantic, potrąca należność z konta w transakcji ACID, aktualizuje stan magazynowy o dostarczony towar i loguje zdarzenie do historii.

### 🧠 Narzędzia Sieciowe (LLM Router)
1. **`dopasuj_narzedzie_llm(dostepne_narzedzia, intencja)`**
   Mechanizm odpornościowy klienta asynchronicznego. Zamiast "na sztywno" wywoływać nazwy narzędzi u zdalnego partnera, przesyła udostępnioną listę z serwera do dodatkowego małego modelu LLM. Model analizując intencję wybiera poprawne narzędzie, co uniezależnia Restaurację od ewentualnych zmian nazewnictwa API w hurtowniach.

---

## 🤝 Protokół CNP (5 Kroków)
Agent ściśle przestrzega zdefiniowanego 5-etapowego algorytmu operacji handlowych:

1. **Identyfikacja Potrzeb**: Szef zleca zakup lub gotowanie dania (braki są wyliczane na podstawie tabeli `przepisy`). Ewentualnie monitor w tle sam zgłasza deficyt.
2. **Dostępność** (`AvailabilityRequest`): Równoległe odpytanie hurtowni o fizyczny stan magazynowy (bez pytania o cenę!).
3. **Oferta i Decyzja** (`CallForProposal`): Zbieranie wycen tylko od hurtowni z dostępnym towarem. Agent wybiera ofertę o najniższym całkowitym koszcie (`total_cost`), sprawdza budżet w bazie danych i wymaga zgody Szefa na zakup.
4. **Finalizacja** (`AcceptProposal`): Transakcja zawierana u zwycięzcy. Zasada milczenia: system nie wysyła wiadomości do przegranych (ich oferty po prostu wygasają).
5. **Dostawa** (`Delivery`): Zewnętrzna hurtownia używa zdalnego narzędzia na naszym serwerze MCP (plik `server.py`), aby zrzucić towar. Baza aktualizuje stany magazynowe i portfel w ramach bezpiecznej transakcji ACID.

---

## ⚙️ Konfiguracja Środowiska (.env)

1. Przed uruchomieniem upewnij się, że posiadasz plik `.env` w głównym katalogu projektu:

```env
GOOGLE_API_KEY=twój_klucz_dostępu_z_Google_AI_Studio
H1_MCP_URL=http://127.0.0.1:8004/mcp/sse
H2_MCP_URL=http://127.0.0.1:8005/sse
R2_MCP_PORT=8003
R2_API_PORT=8022
```
  
2. Upewnij się, że masz aktywne środowisko wirtualne Pythona (`venv`), a następnie zainstaluj wymagane pakiety:

```bash
pip install fastapi uvicorn aiosqlite langchain langchain-core langchain-google-genai langgraph mcp fastmcp pydantic python-dotenv streamlit requests
```

---

## 🚀 Uruchomienie Systemu
Z uwagi na rozproszoną i asynchroniczną naturę aplikacji (oraz działanie GUI), do pełnego uruchomienia Restauracji nr 2 potrzebujesz trzech niezależnych okien terminala.
### Terminal 1: Serwer Nasłuchowy MCP
Ten proces odpowiada za przyjmowanie dostaw (narzędzie `receive_delivery`). Udostępnia serwer MCP na porcie 8003.
```bash
python network/server.py
```
### Terminal 2: Orkiestrator (API FastAPI + Monitor)
Ten proces uruchamia logikę Agenta, API do komunikacji oraz monitor działający w tle (sprawdzanie stanów magazynowych). Działa na porcie 8022.
```bash
python Projekt_A2A.py
```
### Terminal 3: Interfejs Użytkownika (Streamlit)
Panel dowodzenia (Dashboard), za pomocą którego wchodzisz w interakcje z agentem i monitorujesz swoją restaurację. Aplikacja otworzy się automatycznie w Twojej przeglądarce (domyślnie port 8501).
```bash
streamlit run gui.py
```
Po uruchomieniu wszystkich trzech modułów aplikacja jest w pełni gotowa do przyjmowania poleceń i automatycznej współpracy z zewnętrznymi węzłami (Hurtowniami).

---