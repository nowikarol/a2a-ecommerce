# Warehouse 1 (H1) — Agent Hurtowni

Moduł obsługujący **Agenta Hurtowni (H1)** w systemie e-commerce **A2A**.

Aplikacja udostępnia hybrydowy interfejs:

* **FastMCP (SSE)** — publiczny protokół komunikacji agentowej A2A,
* **REST API (FastAPI)** — wewnętrzne operacje handlowe oraz zarządzanie magazynem.

---

## 🏗️ Architektura projektu


```text
warehouse-1/
│
├── main.py                  # Integrator FastAPI i FastMCP
├── README.md                # Dokumentacja modułu
│
├── data/                    # Warstwa danych (SQLite + Pydantic)
│   ├── models.py            # Modele Pydantic (TradeMessage, Item)
│   ├── sql_functions.py     # Operacje bazodanowe 
│   └── warehouse1.db        # Baza danych SQLite
│
└── handlers/                # Warstwa logiki biznesowej
    ├── mcp_tools.py         # Publiczne kontrakty A2A (narzędzia MCP)
    └── internal_ops.py      # Wewnętrzne operacje handlowe
                               # (zakupy u Producenta)
```

---

## ⚙️ Opis modułów i funkcji

### 1. Warstwa danych — `data/`

#### `data/models.py`

Zawiera modele **Pydantic** wykorzystywane do walidacji danych przesyłanych w komunikacji A2A.

**`Item`**

Reprezentuje pojedynczy produkt:

| Pole       | Typ     | Opis             |
| ---------- | ------- | ---------------- |
| `name`     | `str`   | Nazwa produktu   |
| `quantity` | `int`   | Liczba sztuk     |
| `price`    | `float` | Cena jednostkowa |

**`TradeMessage`**

Uniwersalny model koperty komunikacyjnej A2A zawierający m.in.:

* `sender_id` — identyfikator nadawcy,
* `receiver_id` — identyfikator odbiorcy,
* `message_type` — typ komunikatu,
* `item` — informacje o produkcie,
* `total_cost` — całkowity koszt transakcji.

---

#### `data/sql_functions.py`

Moduł odpowiedzialny za bezpośrednią komunikację z bazą **SQLite** oraz wykonywanie operacji CRUD.

**`get_connection()`**

Tworzy i zwraca połączenie z bazą danych z wykorzystaniem `sqlite3.Row`, umożliwiającego dostęp do kolumn po nazwach.

**`init_db(products_list)`**

* tworzy tabelę `products`,
* inicjalizuje bazę początkowym cennikiem,
* wykonuje seedowanie danych przy pierwszym uruchomieniu aplikacji.

**`db_get_product(item_name: str)`**

Pobiera informacje o:

* cenie jednostkowej produktu,
* aktualnym stanie magazynowym.

**`db_update_stock(item_name: str, quantity_change: int, operation: Literal["add", "subtract"])`**

Aktualizuje stan magazynowy:

* `add` — zwiększa stan magazynowy, np. po dostawie od Producenta,
* `subtract` — zmniejsza stan magazynowy, np. po sprzedaży.

---

### 2. Warstwa logiki handlowej — `handlers/`

#### `handlers/mcp_tools.py`

Moduł definiuje narzędzia udostępniane zewnętrznym agentom za pośrednictwem **FastMCP**.

Rejestracja narzędzi odbywa się poprzez:

```python
register_mcp_tools
```

#### `check_availability(item_name, quantity)`

Sprawdza, czy w magazynie znajduje się żądana ilość danego produktu.

Zwraca informację o dostępności towaru.

#### `get_price_proposal(sender_id, item_name, quantity)`

Obsługuje zapytanie:

```text
CALL_FOR_PROPOSAL
```

Jeżeli produkt jest dostępny:

1. pobiera jego cenę,
2. oblicza całkowitą wartość zamówienia,
3. generuje komunikat `PROPOSAL`.

Jeżeli produkt jest niedostępny, zwracany jest:

```text
REJECT_REQUEST
```

#### `finalize_order(sender_id, item_name, quantity, total_cost)`

Obsługuje:

```text
ACCEPT_PROPOSAL
```

Po zaakceptowaniu oferty:

1. aktualizuje stan magazynowy,
2. odejmuje zamówioną ilość produktu,
3. generuje komunikat `DELIVERY`.

---

### 3. Operacje wewnętrzne — `handlers/internal_ops.py`

Moduł obsługuje relację zakupową **Hurtownia → Producent (F1)**.

#### `request_offer(agent_id, producer_url, item_name, quantity)`

Wysyła za pomocą klienta HTTP zapytanie ofertowe do serwera Producenta:

```text
CALL_FOR_PROPOSAL
```

#### `accept_offer(agent_id, producer_url, item_name, quantity, price)`

Wysyła do Producenta akceptację otrzymanej oferty:

```text
ACCEPT_PROPOSAL
```

Po otrzymaniu potwierdzenia:

```text
DELIVERY
```

automatycznie aktualizuje stan magazynowy poprzez:

```python
db_update_stock(..., operation="add")
```

---

## 🚀 Główny integrator — `main.py`

Plik `main.py` integruje serwer **FastAPI** z zasobami **FastMCP**.

### Rejestracja MCP

Endpoint SSE dla komunikacji MCP jest dostępny pod:

```text
/mcp
```

### `GET /products`

Zwraca pełny katalog produktów znajdujących się w bazie danych wraz z:

* nazwą produktu,
* dostępną ilością,
* ceną.

### `POST /a2a/message`

Główny punkt wejścia dla protokołu handlowego **A2A**.

Endpoint:

1. odbiera obiekt `TradeMessage`,
2. analizuje typ komunikatu,
3. wywołuje odpowiednie narzędzie MCP za pomocą:

```python
await mcp.call_tool(...)
```

4. zwraca sparsowany JSON.

### `POST /a2a/buy/request-offer`

Dedykowany endpoint REST uruchamiający proces zakupu towaru od Producenta.

Odpowiada za wysłanie zapytania ofertowego:

```text
CALL_FOR_PROPOSAL
```

### `POST /a2a/buy/accept-offer`

Endpoint REST służący do finalizacji zakupu towaru od Producenta.

Wysyła:

```text
ACCEPT_PROPOSAL
```

---

## 📑 Protokół komunikacji A2A / MCP

Hurtownia realizuje komunikację z innymi agentami zgodnie z poniższym schematem:

| Zdarzenie A2A      | Narzędzie / Endpoint | Wywoływany typ komunikatu | Zwracany typ komunikatu             |
| ------------------ | -------------------- | ------------------------- | ----------------------------------- |
| Zapytanie o cenę   | `get_price_proposal` | `CALL_FOR_PROPOSAL`       | `PROPOSAL` / `REJECT_REQUEST`       |
| Zakup towaru       | `finalize_order`     | `ACCEPT_PROPOSAL`         | `DELIVERY`                          |
| Odmowa oferty      | `handle_message`     | `REJECT_PROPOSAL`         | `REJECTED`                          |
| Zakup u Producenta | `request_offer`      | `CALL_FOR_PROPOSAL`       | `PROPOSAL` *(z serwera Producenta)* |

---

## 🔄 Przepływ przykładowej transakcji

### Sprzedaż towaru z Hurtowni

```text
Agent Klienta
     │
     │ CALL_FOR_PROPOSAL
     ▼
┌───────────────┐
│ Warehouse 1   │
│     (H1)      │
└───────┬───────┘
        │
        │ check_availability()
        │
        ▼
   Dostępny?
    /     \
  TAK      NIE
   │        │
   │        └──────► REJECT_REQUEST
   │
   │ get_price_proposal()
   ▼
 PROPOSAL
   │
   │ ACCEPT_PROPOSAL
   ▼
finalize_order()
   │
   │ db_update_stock(-quantity)
   ▼
 DELIVERY
```

### Zakup towaru od Producenta

```text
Warehouse 1 (H1)
       │
       │ CALL_FOR_PROPOSAL
       ▼
   Producent (F1)
       │
       │ PROPOSAL
       ▼
Warehouse 1 (H1)
       │
       │ ACCEPT_PROPOSAL
       ▼
   Producent (F1)
       │
       │ DELIVERY
       ▼
Warehouse 1 (H1)
       │
       │ db_update_stock(+quantity)
       ▼
   Magazyn uzupełniony
```