# Agent API i Serwer MCP - Restauracja nr 2 (`R2`)

Autonomiczny, w pełni asynchroniczny węzeł handlowy Restauracji nr 2 w systemie wieloagentowym (MAS) łańcucha dostaw. Węzeł komunikuje się za pomocą **Model Context Protocol (FastMCP)**, jest zasilany przez inteligencję **Google Gemini 3.1 Flash-lite (via LangChain)** i ściśle realizuje 5-etapowy standard **Contract Net Protocol (CNP)**.

Aplikacja została zaprojektowana jako nowoczesne REST API na silniku **FastAPI**, gotowe do sterowania przez zewnętrzne narzędzia (np. Orkiestrator).

---

## 📋 Spis Treści
- [Architektura i Rola Agenta](#architektura-i-rola-agenta)
- [Tematyczna Struktura Modułów](#tematyczna-struktura-modułów)
- [Separacja Narzędzi: Serwer MCP vs Agent LLM](#separacja-narzędzi-serwer-mcp-vs-agent-llm)
- [Konfiguracja Środowiska (.env)](#konfiguracja-środowiska-env)
- [Protokół CNP (5 Kroków)](#protokół-cnp-5-kroków)

---

## 🏗️ Architektura i Rola Agenta

Restauracja nr 2 (`R2`) charakteryzuje się proaktywnym podejściem "AI-First" połączonym z twardymi regułami biznesowymi (SQLite):

1. **Relacyjna baza danych SQL (`data/restauracja_2.db`):** Zarządza magazynem surowców (w tym progami bezpieczeństwa), portfelem finansowym (w PLN), recepturami, historią transakcji oraz kolejką zamówień kuchennych. Baza inicjalizuje się automatycznie ze skryptu `.sql` w przypadku pierwszego uruchomienia.
2. **Podejście Human-in-the-Loop:** Model LLM bada rynek, zbiera wyceny i rekomenduje najtańszy zakup, ale zgodnie z propmptem systemowym zawsze zatrzymuje się w Kroku 3, prosząc "Szefa" (Orkiestratora) o ostateczną autoryzację transakcji.
3. **Zasada Braku Domysłów:** Zapobiegająca halucynacjom reguła systemowa gwarantująca, że w przypadku przerwania wątku i utraty kontekstu, model nie odgadnie brakującego surowca, lecz zapyta użytkownika o precyzację.
4. **Automatyczny Reset Wątków:** Gdy Agent umieści w swojej wypowiedzi sygnaturę `[ZADANIE_ZAKONCZONE]`, system samodzielnie wyczyści jego pamięć (LangGraph Checkpointer) przywracając bazowy UUID sesji. Oszczędza to tokeny i zapobiega "przywiązywaniu się" modelu do starych scenariuszy.

---

## 📁 Tematyczna Struktura Modułów

Projekt zachowuje ścisłą separację warstw (Separation of Concerns):

```text
Restauracja_2/
├── data/                       # WARSTWA DANYCH I MODELI
│   ├── models.py               # Modele Pydantic (CNP: CallForProposal, AcceptProposal, Delivery)
│   ├── database.py             # Inicjalizacja bazy SQLite i konfiguracja trybu WAL
│   ├── baza_r2_projektA2A.sql  # Skrypt startowy (schemat i dane początkowe)
│   └── restauracja.db          # Plik bazy danych SQLite (generowany automatycznie)
│
├── agent/                      # WARSTWA INTELIGENCJI
│   ├── agent.py                # Konfiguracja LLM (LangChain, Prompt Systemowy, Pamięć)
│   └── tools.py                # Zestaw prywatnych narzędzi Agenta (SQL + Sieć)
│
├── network/                    # WARSTWA KOMUNIKACJI SIECIOWEJ (MCP / A2A)
│   ├── server.py               # Publiczny Serwer FastMCP (odbiór dostaw)
│   └── client.py               # Asynchroniczny Klient SSE + LLM Router
│
├── Projekt_A2A.py              # Główny punkt wejścia (API FastAPI + Lifespan + Monitor)
└── .env                        # Zmienne środowiskowe (klucze, porty, URL-e)
```

---

## 🛡️ Separacja Narzędzi: Serwer MCP vs Agent LLM

W celu zapewnienia pełnego bezpieczeństwa handlowego, wdrożono ścisły podział narzędzi:

### 1. Publiczny Serwer MCP (`network/server_4.py`) – Dostępny dla Sieci
Wystawia **wyłącznie** bezpieczne punkty styku przy użyciu dekoratora `@mcp.tool()` dla Hurtowni:
* `receive_delivery`: Służy hurtowniom do zrzucenia towaru po wygranym przetargu. Waliduje model `Delivery` przez Pydantic, realizuje transakcję ACID na dwóch tabelach (potrąca z `konto` i dopisuje do `magazyn`) oraz rejestruje ten fakt w logach.

### 2. Prywatne Narzędzia Agenta (`agent/tools_4.py`) – Wykonywane Lokalnie
Dostępne wyłącznie dla "mózgu" Gemini przy użyciu dekoratora `@tool` z biblioteki LangChain:
1. `sprawdz_magazyn()`: Monitorowanie stanu zapasów z bazy.
2. `sprawdz_stan_konta()`: Weryfikacja budżetu (PLN) przed akceptacją ofert.
3. `sprawdz_dostepnosc_w_hurtowniach()`: Współbieżnie odpytuje rynek o surowiec przed zleceniem wycen.
4. `zbierz_oferty_z_hurtowni()`: Współbieżnie wysyła zapytania `CALL_FOR_PROPOSAL` jedynie do tych, którzy mają towar.
5. `finalizuj_zakup()`: Wysyła asynchroniczny komunikat `ACCEPT_PROPOSAL` pod konkretny adres zwycięzcy z zachowaniem reguły milczenia wobec odrzuconych. Zabezpieczony przed wystąpieniem błędu wyprzedanego towaru (Race Condition).
6. `oblicz_braki_dla_dania()`: Pomocnicza logika wyliczeniowa nałożona na przepisy z tabeli SQL.
7. `przygotuj_danie()`: Pobiera składniki, ale w razie deficytu kolejkuje posiłek w specjalnej tabeli `zadania_oczekujace`.
8. `wplac_srodki()`: Rejestracja manualnego zasilenia portfela przez Szefa.
---

## ⚙️ Konfiguracja Środowiska (.env)

Przed uruchomieniem upewnij się, że posiadasz plik `.env` w głównym katalogu projektu z poprawnymi danymi (zaktualizuj porty na te, z których korzystają węzły Hurtowni):

```env
GOOGLE_API_KEY=twój_klucz_dostępu_z_Google_AI_Studio
H1_MCP_URL=http://127.0.0.1:8004/mcp/sse
H2_MCP_URL=http://127.0.0.1:8005/mcp/sse
```

Wymagane biblioteki Pythona (zainstalowane w środowisku wirtualnym venv):

```bash
pip install fastapi uvicorn aiosqlite langchain langchain-core langchain-google-genai langgraph mcp fastmcp pydantic python-dotenv
```

---

## 🤝 Protokół CNP (5 Kroków)

Agent operuje rygorystycznym przepływem:

1. **Dostępność (`AvailabilityRequest`):** Bez odpytywania o cenę, sprawdza najpierw stany fizyczne hurtowni.
2. **Oferta (`CallForProposal`):** Zbiera wyceny jedynie od dostawców ze zweryfikowanym asortymentem.
3. **Decyzja:** Determinacja najlepszej oferty (`total_cost`), weryfikacja zasobów w portfelu i żądanie ostatecznego zatwierdzenia przez operatora API (Orkiestrator).
4. **Finalizacja (`AcceptProposal`):** W razie pomyślnego zakupu wywołuje transakcję (Zasada milczenia). Jeśli hurtownia odeśle błąd `REJECT_PROPOSAL` wynikający np. ze sprzedaży towaru w międzyczasie innej restauracji (Race Condition), Agent od razu przełącza plan na drugą najtańszą ofertę (Fallback).
5. **Dostawa (`Delivery`):** Serwer MCP (niezależny od Agenta LLM) pasywnie nasłuchuje na dostawę towaru, potrącając gotówkę i wpisując ładunek na magazyn.

---

## 🚀 Uruchomienie

Aby podnieść ten węzeł systemu, wymagane są dwa niezależne okna terminala:

### Terminal 1 (Serwer Nasłuchowy MCP – Przyjmujący Towar)
Zainicjuje on bazę SQLite (jeśli jej brak) i nasłuchuje na porcie 8003 na komunikaty DELIVERY z hurtowni

```bash
python network/server.py
```

### Terminal 2 (Główna Aplikacja Agenta i Monitor w Tle)
Wystawia on serwer asynchroniczny API na porcie 8022. Od razu zacznie działać Monitor, sprawdzając w pętli I/O stany magazynowe

```bash
python Projekt_A2A.py
```