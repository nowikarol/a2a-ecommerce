# Serwer MCP i Agent Gemini - Restauracja nr 1 (`restaurant-1`)

Autonomiczny węzeł handlowy Restauracji nr 1 w systemie wieloagentowym (MAS) łańcucha dostaw (Producent – Hurtownie – Restauracje), komunikujący się za pomocą **Model Context Protocol (MCP)**, zasilany przez **Google AI Studio (Gemini 3.6 Flash)** oraz realizujący protokół przetargowy **Contract Net Protocol (CNP)**.

---

## 📋 Spis Treści
- [Architektura i Rola Agenta](#architektura-i-rola-agenta)
- [Tematyczna Struktura Modułów](#tematyczna-struktura-modułów)
- [Separacja Narzędzi: Serwer MCP vs Agent LLM](#separacja-narzędzi-serwer-mcp-vs-agent-llm)
- [Konfiguracja Gemini API (.env)](#konfiguracja-gemini-api-env)
- [Mózg Agenta (agent/agent.py)](#mózg-agenta-agentagentpy)
- [Zgodność ze Schematami docs/schemas/](#zgodność-ze-schematami-docsschemas)
- [Uruchomienie i Testy](#uruchomienie-i-testy)

---

## 🍕 Architektura i Rola Agenta

Restauracja nr 1 (`R1`):
1. **Relacyjna baza danych SQL (`data/database.py`, `data/restaurant.db`):** Zarządza magazynem 11 włoskich surowców (flour, passata, mozzarella, parmigiano reggiano, burrata, buffala, prosciutto cotto, prosciutto crudo, arugula, lamb's lettuce, salami) oraz autentycznymi recepturami przy użyciu zapytań SQL z transakcjami ACID.
2. **Portfel finansowy i budżet zakupowy (`financial_account`):** Śledzi saldo środków w walucie PLN, rejestruje historię operacji w tabeli `transactions` i weryfikuje wypłacalność przed akceptacją ofert hurtowni.
3. **Autonomicznie reaguje na braki:** Przy wykryciu stanu na lub poniżej progu bezpieczeństwa emituje zapytania przetargowe.
4. **Negocjuje w Contract Net Protocol (CNP):**
   - Weryfikuje dostępność surowców w hurtowniach (`AVAILABILITY_REQUEST`).
   - Wysyła zapytania `CALL_FOR_PROPOSAL` (`request-offer.json`).
   - Odbiera oferty `PROPOSAL` (`response-offer.json`).
   - **Deterministycznie wybiera ofertę o najniższym koszcie:**
     $$\min(\text{total\_cost})$$
   - Generuje `ACCEPT_PROPOSAL` (`accept-offer.json`) wyłącznie dla wybranego sprzedawcy. W razie odrzucenia (`reject`) przez sprzedawcę z powodu braku towaru, automatycznie przechodzi do kolejnej oferty (fallback). Pozostali sprzedawcy nie otrzymują żadnych wiadomości (oferty milcząco wygasają).
   - Odbiera dostawę towaru na publicznym serwerze MCP, powiększa zapasy i rozlicza płatność z portfela (`receive_delivery`).
5. **Mózg LLM (Google AI Studio / Gemini):** Steruje narzędziami biznesowymi przez pętlę tool-calling z modelem `gemini-3.6-flash` (oraz automatycznym fallbackiem `gemini-3.1-flash-lite`).

---

## 📁 Tematyczna Struktura Modułów

Kod podzielono na 3 spójne filary tematyczne (dane, logika agenta, sieć) oraz testy:

```text
restaurant-1/
├── data/                         # WARSTWA DANYCH I MODELI
│   ├── __init__.py               # Eksporty modeli i funkcji bazodanowych
│   ├── models.py                 # Modele Pydantic v2 (komunikaty CNP, zamówienia, portfel)
│   ├── database.py               # Relacyjna baza SQLite (tabele, ACID, seeding)
│   ├── view_db.py                # Narzędzie CLI do inspekcji bazy SQLite
│   └── restaurant.db             # Plik bazy danych SQLite
│
├── agent/                        # WARSTWA INTELIGENCJI I DZIAŁAŃ
│   ├── __init__.py               # Eksporty RestaurantBrain i RestaurantAgent
│   ├── agent.py                  # Mózg LLM Gemini (pętla tool-calling, prompt systemowy)
│   └── tools.py                  # Logika biznesowa RestaurantAgent w SQL, GEMINI_TOOLS, execute_tool
│
├── network/                      # WARSTWA KOMUNIKACJI SIECIOWEJ (MCP / A2A)
│   ├── __init__.py               # Eksporty klienta i serwera sieciowego
│   ├── server.py                 # Serwer MCP A2A (udostępnia TYLKO: receive_delivery, get_node_info)
│   └── mcp_client.py             # Klient MCP SSE do odpytywania hurtowni H1 i H2
│
├── tests/                        # PAKIET TESTÓW AUTOMATYCZNYCH
│   ├── __init__.py
│   └── test_restaurant.py        # 50 testów jednostkowych i integracyjnych (pytest)
│
├── config.py                     # Centralna konfiguracja środowiska, modeli i ścieżek
├── requirements.txt              # Zależności projektu
├── README.md                     # Dokumentacja architektury
└── .env                          # Plik zmiennych środowiskowych
```

---

## 🛡️ Separacja Narzędzi: Serwer MCP vs Agent LLM

W celu zapewnienia bezpieczeństwa handlowego i eliminacji wycieków danych w architekturze A2A wprowadzono ścisły rozdział ról:

### 1. Publiczny Serwer MCP (`network/server.py`) – Dostępny dla Hurtowni (Port 8002)
Wystawia **wyłącznie** bezpieczne punkty styku protokołu CNP:
* `receive_delivery(delivery_data)`: Odbiera dostawę towaru od wygranej hurtowni, weryfikuje zgodność ze schematem `delivery.json`, aktualizuje stan magazynowy i rozlicza płatność z portfela `R1_WALLET`.
* `get_node_info()`: Zwraca publiczną tożsamość węzła i obsługiwane protokoły.

> [!NOTE]
> Narzędzia stanu portfela, stanu spiżarni i algorytmów zakupowych **nie są wystawione do sieci**, dzięki czemu hurtownie nie mają możliwości podglądu salda restauracji w celu manipulowania cenami przetargowymi.

### 2. Wewnętrzne Narzędzia Agenta Gemini (`agent/tools.py` ➔ `GEMINI_TOOLS`) – Wykonywane Lokalnie
Dostępne wyłącznie dla lokalnego mózgu LLM (`agent/agent.py`) w procesie Pythona:
1. `check_inventory()`: Monitoruje stan spiżarni, progi bezpieczeństwa i status składników.
2. `get_financial_status()`: Zwraca aktualne saldo portfela i historię transakcji.
3. `deposit_funds(amount, description)`: Wpłata środków na konto operacyjne.
4. `consume_ingredients(dish_name, quantity)`: Odejmuje surowce po przygotowaniu dań.
5. `create_procurement_request(item_name, quantity, receiver_id)`: Przygotowuje komunikat `CALL_FOR_PROPOSAL`.
6. `check_wholesaler_availability(item_name, quantity, wholesalers)`: Bada dostępność surowca w hurtowniach H1/H2 przed wysłaniem zapytań cenowych.
7. `request_quotes_and_evaluate(item_name, quantity, wholesalers, auto_order)`: Dwuetapowy proces zakupowy CNP (dostępność ➔ oferty cenowe ➔ min(total_cost) ➔ weryfikacja budżetu).
8. `evaluate_proposals(proposals_list)`: Wybiera zwycięzcę przetargu.
9. `check_and_trigger_procurement(wholesalers)`: Autonomiczny monitor zaopatrzenia w bazie SQL.

---

## ⚙️ Konfiguracja Gemini API (.env)

Uzupełnij klucz API Google AI Studio w `restaurant-1/.env`:
```env
GEMINI_API_KEY=twoj_klucz_z_google_ai_studio
GEMINI_MODEL=gemini-3.6-flash
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
```

---

## 🧠 Mózg Agenta (`agent/agent.py`)

Agent wykorzystuje oficjalny endpoint Google AI Studio z zachowaniem struktury `thought_signature`:
1. Pobiera zapytanie użytkownika lub wyzwalacz autonomiczny.
2. Wysyła zapytanie do Gemini z deklaracjami `tools=GEMINI_TOOLS`.
3. Obsługuje zdarzenia `response.choices[0].message.tool_calls`.
4. Wykonuje odpowiednie funkcje poprzez lokalne `execute_tool()`.
5. Pętla powtarza się, dopóki model nie zwróci ostatecznej odpowiedzi.

### Przykładowe użycie CLI:
```bash
# Pytanie bezpośrednie do agenta (wymaga klucza w .env):
python restaurant-1/agent/agent.py --prompt "Jaki jest aktualny stan spiżarni i co powinniśmy dokupić?"

# Autonomiczny audyt zapasów i wywołanie CNP w przypadku braków:
python restaurant-1/agent/agent.py --audit

# Tryb interaktywny:
python restaurant-1/agent/agent.py
```

---

## 📑 Zgodność ze Schematami `docs/schemas/`

| Komunikat | Plik Schematu | Typ wiadomości | Format elementu `item` |
|---|---|---|---|
| Sprawdzenie dostępności | `availability-request.json` | `AVAILABILITY_REQUEST` | `{"name": str, "quantity": int}` |
| Odpowiedź o dostępności | `availability-response.json` | `AVAILABILITY_RESPONSE` | `{"name": str, "quantity": int}`, `is_available: bool`, `available_quantity: int` |
| Zapytanie ofertowe | `request-offer.json` | `CALL_FOR_PROPOSAL` | `{"name": str, "quantity": int}` |
| Oferta cenowa | `response-offer.json` | `PROPOSAL` | `{"name": str, "quantity": int, "price": float}`, `total_cost` |
| Akceptacja oferty | `accept-offer.json` | `ACCEPT_PROPOSAL` | `{"name": str, "quantity": int, "price": float}`, `total_cost` |
| Odrzucenie zamówienia (brak towaru w Kroku 4) | `reject.json` | `REJECT_PROPOSAL` | `{"name": str, "quantity": int}` |
| Dostawa towaru | `delivery.json` | `DELIVERY` | `{"name": str, "quantity": int, "price": float}`, `total_cost` |

---

## 🚀 Uruchomienie i Testy

### 1. Uruchomienie publicznego serwera MCP:
```bash
python restaurant-1/network/server.py
```
*(Domyślny transport: stdio, obsługa SSE przez `--transport sse --port 8002`)*

### 2. Autonomiczny audyt i zaopatrzenie spiżarni (CLI Agenta):
```bash
python restaurant-1/agent/agent.py --audit
```

### 3. Inspekcja bazy danych SQLite (spiżarnia, receptury, portfel, transakcje):
```bash
python restaurant-1/data/view_db.py
```

### 4. Testy automatyczne (pytest):
```bash
pytest restaurant-1/tests -v
```
*(Zestaw 50 testów automatycznych pokrywa modele Pydantic, reguły deterministyczne CNP, narzędzia Gemini i SQL, dwuetapową weryfikację dostępności oraz separację ról na serwerze MCP)*
