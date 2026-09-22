# Serwer MCP Producenta (`P1`)

Autonomiczny węzeł podażowy Producenta P1 w systemie łańcucha dostaw (Producent – Hurtownie – Restauracje), komunikujący się za pomocą **Model Context Protocol (MCP)**. 

Serwer pełni **wyłącznie rolę Sprzedającego** (nie kupuje towarów od innych węzłów)[cite: 2]. Węzeł działa w 100% deterministycznie – opiera się na twardej logice biznesowej i weryfikacji bazy danych, bez udziału modeli językowych (LLM).

---

## 📋 Spis Treści
- [Architektura i Rola Serwera](#architektura-i-rola-serwera)
- [Struktura Plików](#struktura-plików)
- [Wystawiane Narzędzia MCP (Protokół Handlowy)](#wystawiane-narzędzia-mcp-protokół-handlowy)
- [Baza Danych (`setup_db.py`)](#baza-danych-setup_dbpy)
- [Narzędzia Debugowania (GUI & Testy)](#narzędzia-debugowania-gui--testy)
- [Uruchomienie i Adresy Połączeń](#uruchomienie-i-adresy-połączeń)

---

## 🏭 Architektura i Rola Serwera

Węzeł `P1`:
1. **Relacyjna baza danych SQL (`setup_db.py`, `producer.db`):** Przechowuje katalog 11 surowców (m.in. mąka, passata, mozzarella, prosciutto)[cite: 1] wraz z ich cenami i aktualnym stanem magazynowym, a także pełną historię transakcji[cite: 1, 2].
2. **Serwer MCP (`MCP_server.py`, port 8001, transport SSE):** Główny silnik aplikacji oparty na FastMCP[cite: 2]. Udostępnia narzędzia do weryfikacji dostępności i ofertowania. Przelicza ceny katalogowe, uwzględniając sztywne reguły rabatowe (np. 10% rabatu dla stałego klienta `H1`)[cite: 2]. 
3. **Automatyzacja dostaw:** Po zaakceptowaniu oferty przez kupującego, serwer samodzielnie nawiązuje połączenie z serwerem nabywcy i wywołuje na nim narzędzie `receive_delivery`, zamykając proces handlowy po stronie sprzedawcy[cite: 2].

---

## 📁 Struktura Plików

```text
producer-p1/
├── MCP_server.py        # Główny serwer FastMCP (SSE, port 8001) obsługujący logikę sprzedawcy
├── gui.py               # Graficzny dashboard webowy (Flask) do podglądu bazy i testowania JSON
├── setup_db.py          # Skrypt inicjalizujący i resetujący bazę danych SQLite
├── start_server.bat     # Launcher: ustawia bazę danych i uruchamia MCP_server.py
├── test.py              # Skrypt testowy sprawdzający, czy serwer poprawnie odpowiada
└── producer.db          # Plik bazy danych SQLite (generowany automatycznie)
```

---

## 🛠️ Wystawiane Narzędzia MCP (Protokół Handlowy)

Serwer wystawia 3 standardowe narzędzia Sprzedającego, obsługujące kroki protokołu CNP[cite: 2]:

1. **`check_availability`**
   - Odbiera: `sender_id`, `receiver_id`, `item_name`, `quantity`[cite: 2].
   - Działanie: Sprawdza, czy żądana ilość towaru znajduje się fizycznie w magazynie (`stock_quantity`) i zwraca `AVAILABILITY_RESPONSE`[cite: 2].

2. **`request_offer`**
   - Odbiera: `sender_id`, `receiver_id`, `item_name`, `quantity`[cite: 2].
   - Działanie: Weryfikuje dostępność w magazynie. Jeśli towar jest dostępny, oblicza cenę na podstawie katalogu (uwzględniając ewentualne rabaty) i zwraca ofertę `PROPOSAL` lub odrzucenie `REJECT_PROPOSAL` w przypadku braku towaru[cite: 2].

3. **`accept_offer`**
   - Odbiera: `sender_id`, `receiver_id`, `item_name`, `quantity`, `price`, `total_cost`[cite: 2].
   - Działanie: Waliduje poprawność obliczeń i weryfikuje FAKTYCZNY stan magazynowy w transakcji atomowej[cite: 2]. W przypadku sukcesu: odejmuje towar z magazynu, zapisuje transakcję i automatycznie wysyła `DELIVERY` na serwer kupującego (wywołuje `receive_delivery`)[cite: 2].

---

## 🗄️ Baza Danych (`setup_db.py`)

Skrypt `setup_db.py` generuje plik `producer.db`[cite: 1] z trzema tabelami:

| Tabela | Opis |
|---|---|
| `products` | Katalog surowców: `product_code`, `name`, `unit_price`, `stock_quantity`, `unit`[cite: 1]. |
| `production_plan` | Plan produkcji: `product_code`, `production_date`, `quantity`, `status`[cite: 1]. |
| `sales_transactions` | Rejestr sprzedaży: `product_code`, `quantity`, `unit_price`, `total_cost`, `buyer_id`, `transaction_date`[cite: 1]. |

Uruchomienie ręczne (odbudowuje strukturę i przywraca dane startowe):
```bash
python setup_db.py
```

---

## 📊 Narzędzia Debugowania (GUI & Testy)

Węzeł został wyposażony w narzędzia ułatwiające monitorowanie procesów bez zagłębiania się w logi terminala:

* **Dashboard Webowy (`gui.py`)**: Interfejs graficzny pozwalający na podgląd bazy danych `producer.db` w czasie rzeczywistym. Posiada wbudowany tester zapytań (Payload Tester), który umożliwia ręczne wysyłanie spreparowanych JSON-ów z wywołaniem narzędzi do serwera MCP oraz konsolę SQL do manipulacji bazą.
* **Skrypt Testowy (`test.py`)**: Prosty program wysyłający pojedynczy sygnał do serwera, weryfikujący czy aplikacja `MCP_server.py` działa i odpowiada na zapytania w sieci.

---

## 🚀 Uruchomienie i Adresy Połączeń

### 🔌 Adres Połączenia MCP (SSE Endpoint)
Inne węzły (kupujący) oraz klienci MCP powinni łączyć się z serwerem pod adresem:
```text
[http://127.0.0.1:8001/sse](http://127.0.0.1:8001/sse)
```

### Automatyczne Uruchomienie (Windows)
Najprostszym sposobem na inicjalizację bazy i uruchomienie serwera jest użycie dostarczonego skryptu wsadowego:
```cmd
start_server.bat
```

### Uruchomienie Dashboardu GUI (Opcjonalne, w osobnym terminalu)
Aby uzyskać graficzny podgląd działania bazy w trakcie operacji, włącz aplikację GUI:
```bash
python gui.py
```
Panel będzie dostępny w przeglądarce pod adresem `http://127.0.0.1:5000` (lub `http://127.0.0.1:5050`).