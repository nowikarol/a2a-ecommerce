# Serwer MCP i Agent LangChain (Gemini) - Restauracja nr 2 (`R2`)

Autonomiczny węzeł handlowy Restauracji nr 2 w systemie wieloagentowym (MAS) łańcucha dostaw (Producent – Hurtownie – Restauracje). Węzeł komunikuje się za pomocą **Model Context Protocol (FastMCP)**, jest zasilany przez inteligencję **Google Gemini 1.5 Flash (via LangChain)** oraz realizuje ustandaryzowany protokół przetargowy **Contract Net Protocol (CNP)**.

---

## 📋 Spis Treści
- [Architektura i Rola Agenta](#architektura-i-rola-agenta)
- [Tematyczna Struktura Modułów](#tematyczna-struktura-modułów)
- [Separacja Narzędzi: Serwer MCP vs Agent LLM](#separacja-narzędzi-serwer-mcp-vs-agent-llm)
- [Konfiguracja Środowiska (.env)](#konfiguracja-środowiska-env)
- [Mózg Agenta i Zarządzanie Wątkami](#mózg-agenta-i-zarządzanie-wątkami)
- [Uruchomienie i Obsługa](#uruchomienie-i-obsługa)

---

## 🍕 Architektura i Rola Agenta

Restauracja nr 2 (`R2`) charakteryzuje się nowoczesnym podejściem "AI-First":

1. **Relacyjna baza danych SQL (`data/restauracja_2.db`):** Zarządza magazynem surowców, portfelem finansowym (w PLN), autentycznymi recepturami oraz historią transakcji. Baza inicjalizuje się automatycznie przy pierwszym uruchomieniu.
2. **Podejście AI-First w decyzyjności:** Zamiast "sztywnych" reguł w kodzie Pythona, to sam model językowy (Gemini) analizuje zebrane oferty, porównuje koszty i decyduje o wyborze najtańszej hurtowni, zachowując przy tym pełną świadomość posiadanego budżetu.
3. **Negocjacje w Contract Net Protocol (CNP):**
   - Wysyła zapytania `CALL_FOR_PROPOSAL` do hurtowni za pośrednictwem zapytań asynchronicznych SSE.
   - Odbiera i analizuje oferty `PROPOSAL` w formacie ustandaryzowanych modeli Pydantic.
   - Generuje decyzje `ACCEPT_PROPOSAL` dla wygranego oraz `REJECT_PROPOSAL` dla pozostałych.
4. **Odbiór dostaw i rozliczenia:** Odbiera towar poprzez publiczny serwer MCP (`receive_delivery`), powiększa zapasy i potrąca środki z tabeli konta.

---

## 📁 Tematyczna Struktura Modułów

Projekt został podzielony na odseparowane warstwy (Separation of Concerns), co gwarantuje łatwe utrzymanie kodu i bezpieczeństwo:

```text
Restauracja_2/
├── data/                         # WARSTWA DANYCH I MODELI
│   ├── models.py                 # Modele Pydantic (CNP: CallForProposal, AcceptProposal itp.)
│   ├── database.py               # Inicjalizacja bazy SQLite
│   ├── baza_r2_projektA2A.sql    # Skrypt startowy (schemat i dane początkowe)
│   └── restauracja_2.db          # Plik bazy danych SQLite (generowany automatycznie)
│
├── agent/                        # WARSTWA INTELIGENCJI I DZIAŁAŃ LOKALNYCH
│   ├── agent.py                  # Konfiguracja LLM (LangChain, Prompt Systemowy, Pamięć)
│   └── tools.py                  # Zestaw prywatnych narzędzi Agenta (dekorator @tool)
│
├── network/                      # WARSTWA KOMUNIKACJI SIECIOWEJ (MCP / A2A)
│   ├── server.py                 # Demon nasłuchujący MCP (FastMCP + ngrok)
│   └── client.py                 # Klient SSE do komunikacji z serwerami Hurtowni
│
├── Projekt_A2A.py                # Główny punkt wejścia i pętla czatu z Agentem (Szefem)
├── .env                          # Zmienne środowiskowe (klucze API)
└── README.md                     # Dokumentacja projektu
```

---

## 🛡️ Separacja Narzędzi: Serwer MCP vs Agent LLM

W celu zapewnienia pełnego bezpieczeństwa handlowego (ochrona przed wglądem w saldo i magazyn ze strony innych węzłów), wdrożono ścisły podział narzędzi:

### 1. Publiczny Serwer MCP (`network/server.py`) – Dostępny dla Sieci
Wystawia **wyłącznie** bezpieczne punkty styku przy użyciu dekoratora `@mcp.tool()`:
* `accept_delivery`: Służy hurtowniom do zrzucenia towaru po wygranym przetargu. Rejestruje fakturę, dodaje towar do magazynu i pobiera środki z tabeli konta.

### 2. Prywatne Narzędzia Agenta (`agent/tools.py`) – Wykonywane Lokalnie
Dostępne wyłącznie dla "mózgu" Gemini przy użyciu dekoratora `@tool` z biblioteki LangChain:
1. `sprawdz_magazyn()`: Monitorowanie stanu zapasów.
2. `oblicz_braki_dla_dania()`: Moduł kuchenny – weryfikacja potrzebnych składników z receptur.
3. `sprawdz_stan_konta()`: Weryfikacja budżetu (PLN) przed akceptacją ofert.
4. `zbierz_oferty_z_hurtowni()`: Wysyła asynchroniczne zapytania `CALL_FOR_PROPOSAL` do zdefiniowanych hurtowni.
5. `finalizuj_zakup()`: Wysyła akceptację do zwycięzcy i odrzucenie do przegranych.
6. `odrzuc_wszystkie_oferty()`: Anuluje przetarg w przypadku braku zgody Szefa.

---

## ⚙️ Konfiguracja Środowiska (.env)

Przed uruchomieniem upewnij się, że posiadasz plik `.env` w głównym katalogu projektu:

```env
GOOGLE_API_KEY=twój_klucz_dostępu_z_Google_AI_Studio
NGROK_TOKEN=twój_authtoken_ngrok
```

Wymagane biblioteki Pythona (zainstalowane w środowisku wirtualnym venv):

```bash
pip install langchain langchain-core langchain-google-genai langgraph mcp fastmcp nest-asyncio pyngrok pydantic python-dotenv
```

---

## 🧠 Mózg Agenta i Zarządzanie Wątkami

Nasz agent wykorzystuje architekturę **LangGraph (MemorySaver)** do utrzymywania kontekstu rozmowy. 
Aby zapobiec zjawisku przepełnienia kontekstu LLM (tzw. "halucynacji" spowodowanych zbyt długą historią wcześniejszych zakupów), proces `Projekt_A2A.py` posiada wbudowane zarządzanie cyklem życia pamięci.

Wydanie komendy `reset` w konsoli generuje nowy identyfikator wątku (za pomocą biblioteki `uuid`), pozwalając agentowi rozpocząć nowe zadanie zakupowe z tzw. "czystą kartą", bez utraty danych zapisanych trwale w bazie SQL.

---

## 🚀 Uruchomienie i Obsługa

Architektura mikroserwisowa wymaga uruchomienia procesów w dwóch osobnych terminalach:

### Krok 1: Uruchomienie Serwera Publicznego (Terminal 1)
Serwer działa jako demon w tle, tunelując ruch przez ngrok i oczekując na dostawy:

```bash
python network/server.py
```

### Krok 2: Uruchomienie Panelu Agenta (Terminal 2)
Interfejs czatu dla "Szefa" restauracji. Służy do zlecenia audytów i akceptacji zakupów.

```bash
python Projekt_A2A.py
```

### Przydatne komendy w czacie (Terminal 2):
`reset` – Czyści krótkotrwałą pamięć agenta i otwiera nowy wątek zakupowy.
`wyjscie` – Zamyka panel Agenta (serwer w Terminalu 1 działa nadal).
