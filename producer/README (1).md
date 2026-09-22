# Serwer MCP i Agent Gemini - Fabryka nr 1 (`F1`)

Autonomiczny węzeł podażowy Fabryki F1 w systemie wieloagentowym (MAS) łańcucha dostaw (Producent – Hurtownie – Restauracje), komunikujący się za pomocą **Model Context Protocol (MCP)**, zasilany przez **Gemini API** (`google-genai`) i realizujący komunikację **A2A (Agent-to-Agent)** opartą na wiadomościach typu `CALL_FOR_PROPOSAL` / `PROPOSAL` / `REJECT_PROPOSAL`.

---

## 📋 Spis Treści
- [Architektura i Rola Agenta](#architektura-i-rola-agenta)
- [Struktura Plików](#struktura-plików)
- [Separacja Narzędzi: Serwer MCP vs Agent A2A](#separacja-narzędzi-serwer-mcp-vs-agent-a2a)
- [Baza Danych (`setup_db.py`)](#baza-danych-setup_dbpy)
- [Konfiguracja Środowiska (.env)](#konfiguracja-środowiska-env)
- [Mózg Agenta (`agent_server.py`)](#mózg-agenta-agent_serverpy)
- [Uruchomienie](#uruchomienie)

---

## 🏭 Architektura i Rola Agenta

Fabryka nr 1 (`F1`):
1. **Relacyjna baza danych SQL (`setup_db.py`, `factory.db`):** przechowuje katalog 11 surowców/produktów (mąka, passata, mozzarella, parmigiano reggiano, burrata, mleko bawole, prosciutto cotto/crudo, rukola, roszponka, salami) wraz z ceną jednostkową i stanem magazynowym, a także plan produkcji (`production_plan`) z ilościami zaplanowanymi na najbliższe dni.
2. **Serwer MCP (`mcp_server.py`, port 8000, transport SSE):** udostępnia surowy, deterministyczny odczyt z bazy — wycenę katalogową oraz dostępność (stan magazynowy + planowana produkcja) — bez żadnej logiki negocjacyjnej.
3. **Agent A2A (`agent_server.py`, FastAPI, port 8001):** odbiera zapytania `CALL_FOR_PROPOSAL` od odbiorców (np. Hurtowni R1), pobiera dane bazowe z MCP, a następnie **Gemini (`gemini-2.5-flash`)** podejmuje decyzję handlową (trzymanie ceny katalogowej lub przyznanie rabatu stałemu klientowi) i zwraca gotową wiadomość `PROPOSAL`/`REJECT_PROPOSAL` w formacie JSON.
4. **Tunelowanie ngrok:** przy starcie agent automatycznie tworzy publiczny tunel do lokalnego serwera MCP (port 8000), zapisuje adres do `ngrok_url.txt` i kopiuje go do schowka, aby udostępnić go innym węzłom sieci (np. hurtowniom).

---

## 📁 Struktura Plików

W przeciwieństwie do modularnej architektury `restaurant-1` (podział na `data/` / `agent/` / `network/`), węzeł `F1` jest zorganizowany jako zestaw skryptów w jednym katalogu:

```text
factory-f1/
├── mcp_server.py        # Serwer MCP (FastMCP, SSE, port 8000) — wycena i dostępność
├── agent_server.py      # Agent A2A (FastAPI, port 8001) + Gemini + tunel ngrok
├── setup_db.py          # Tworzenie i seedowanie bazy SQLite (factory.db)
├── start_servers.bat    # Launcher: uruchamia oba serwery i pokazuje adres ngrok
├── factory.db           # Plik bazy danych SQLite (generowany przez setup_db.py)
├── ngrok_url.txt         # Publiczny adres MCP wygenerowany przy starcie (auto)
└── .env                  # Zmienne środowiskowe (GEMINI_API_KEY, NGROK_*)
```

---

## 🛡️ Separacja Narzędzi: Serwer MCP vs Agent A2A

### 1. Serwer MCP (`mcp_server.py`) – Dostępny przez `/sse` (Port 8000)
Wystawia trzy narzędzia czysto informacyjne, bez logiki negocjacyjnej:
* `get_preliminary_price(product_code, quantity, sender_id, receiver_id)`: zwraca wstępną wycenę katalogową (`PROPOSAL`) lub `REJECT_PROPOSAL`, jeśli produkt nie istnieje w bazie.
* `check_availability(product_code, quantity, sender_id, receiver_id)`: sumuje bieżący stan magazynowy i planowaną produkcję (`status = 'planned'`) i zwraca maksymalną możliwą do zaoferowania ilość.
* `get_service_directory()`: zwraca mapę endpointów F1, informując inne agenty, kiedy użyć MCP (surowa cena/dostępność), a kiedy endpointu A2A (negocjacja).

> [!NOTE]
> Serwer MCP nie zawiera żadnej logiki rabatowej ani decyzyjnej — to czysta warstwa danych. Decyzje handlowe (np. przyznanie rabatu) zapadają wyłącznie po stronie agenta A2A, zasilanego przez Gemini.

### 2. Agent A2A (`agent_server.py`) – FastAPI (Port 8001)
* `POST /a2a/rfq`: odbiera wiadomość `CALL_FOR_PROPOSAL`, łączy się z serwerem MCP po dane bazowe (`get_preliminary_price`), przekazuje kontekst do Gemini razem z `SYSTEM_PROMPT` (zasady biznesowe: domyślnie cena katalogowa, do 10% rabatu dla stałego klienta `R1`) i zwraca sparsowany JSON odpowiedzi (`PROPOSAL` lub `REJECT_PROPOSAL`).
* `GET /a2a/discovery`: zwraca „wizytówkę” agenta (`agent_id: F1`, obsługiwane zdolności i reguły interakcji) dla innych węzłów sieci.

---

## 🗄️ Baza Danych (`setup_db.py`)

Tworzy plik `factory.db` z dwiema tabelami:

| Tabela | Opis |
|---|---|
| `products` | `product_code`, `name`, `unit_price`, `stock_quantity`, `unit` — katalog 11 produktów z przykładowymi cenami i stanami magazynowymi |
| `production_plan` | `product_code`, `production_date`, `quantity`, `status` (`'planned'`) — harmonogram planowanej produkcji na kolejne dni, używany przez `check_availability` |

Uruchomienie (tworzy bazę, jeśli nie istnieje, i wstawia dane przykładowe przez `INSERT OR IGNORE`):
```bash
python setup_db.py
```

---

## ⚙️ Konfiguracja Środowiska (`.env`)

Plik `.env` w katalogu głównym powinien zawierać:
```env
GEMINI_API_KEY=twoj_klucz_gemini
NGROK_API_KEY=twoj_klucz_ngrok
# lub, alternatywnie:
NGROK_AUTHTOKEN=twoj_klucz_ngrok
```

Zależności (na podstawie importów w kodzie):
```bash
pip install fastapi uvicorn fastmcp python-dotenv google-genai pyngrok
```

---

## 🧠 Mózg Agenta (`agent_server.py`)

Przy każdym żądaniu `CALL_FOR_PROPOSAL`:
1. Agent łączy się z serwerem MCP (`Client(MCP_SERVER_URL)`) i wywołuje `get_preliminary_price`, aby pobrać dane bazowe (cenę katalogową).
2. Buduje kontekst dla LLM: treść przychodzącej wiadomości A2A + wynik z MCP.
3. Wysyła zapytanie do **Gemini** (`gemini-2.5-flash`) z `SYSTEM_PROMPT` wymuszającym odpowiedź w czystym JSON (`response_mime_type="application/json"`).
4. Parsuje odpowiedź modelu i zwraca ją bezpośrednio jako wynik endpointu `/a2a/rfq`.

Model podejmuje decyzję zgodnie z zasadami biznesowymi zawartymi w prompcie systemowym: domyślnie trzyma się ceny z MCP, ale może przyznać do 10% rabatu, jeśli `sender_id` to stały klient (`R1`).

---

## 🚀 Uruchomienie

### Automatycznie (zalecane, Windows)
```bash
start_servers.bat
```
Skrypt:
1. Czyści stare procesy `ngrok.exe` oraz procesy nasłuchujące na porcie 8000.
2. Usuwa stary `ngrok_url.txt`.
3. Uruchamia serwer MCP (`mcp_server.py`) w osobnym oknie i czeka 5 sekund na jego start.
4. Uruchamia agenta A2A (`agent_server.py`), który sam tworzy tunel ngrok dla portu MCP.
5. Czeka na wygenerowanie `ngrok_url.txt` i wyświetla publiczny adres MCP gotowy do wysłania innym węzłom (adres jest też automatycznie kopiowany do schowka).

### Ręcznie
```bash
# 1. Utworzenie i zaseedowanie bazy danych
python setup_db.py

# 2. Uruchomienie serwera MCP (port 8000)
python mcp_server.py

# 3. W osobnym terminalu — uruchomienie agenta A2A + tunel ngrok (port 8001)
python agent_server.py
```

Po starcie:
- Serwer MCP nasłuchuje lokalnie na `http://0.0.0.0:8000/sse`.
- Agent A2A nasłuchuje na `http://0.0.0.0:8001`, wystawiając `/a2a/rfq` i `/a2a/discovery`.
- Publiczny adres MCP (przez ngrok) trafia do `ngrok_url.txt` i schowka — to on jest przekazywany innym agentom w sieci (np. hurtowniom), aby mogli sprawdzić ceny/dostępność przed wysłaniem `CALL_FOR_PROPOSAL` na `/a2a/rfq`.
