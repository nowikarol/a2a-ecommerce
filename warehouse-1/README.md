# Warehouse 1 (H1) — Agent Hurtowni

**Warehouse 1 (H1)** to agent hurtowni w systemie e-commerce opartym na komunikacji **A2A (Agent-to-Agent)**.

H1 pełni dwie role:

* **Sprzedawcy** — obsługuje klientów, przygotowuje oferty i realizuje sprzedaż.
* **Kupującego** — pozyskuje towary od Producenta (F1) i przyjmuje dostawy.

Aplikacja udostępnia dwa interfejsy:

* **FastMCP (SSE)** — publiczne narzędzia wykorzystywane w komunikacji A2A,
* **REST API (FastAPI)** — operacje wewnętrzne, finanse, magazyn oraz zakupy u Producenta.

Komunikacja handlowa wykorzystuje mechanizmy **Contract Net Protocol (CNP)**, m.in. `CALL_FOR_PROPOSAL`, `PROPOSAL`, `ACCEPT_PROPOSAL` i `REJECT_PROPOSAL`.

---

## 🏗️ Architektura

```text
warehouse-1/
│
├── main.py                  # FastAPI + FastMCP
├── README.md
│
├── data/
│   ├── models.py            # Modele Pydantic
│   ├── sql_functions.py     # Operacje SQLite
│   └── warehouse.db         # Baza danych
│
└── handlers/
    ├── mcp_tools.py         # Publiczne narzędzia A2A / MCP
    └── internal_ops.py      # Zakupy u Producenta
```

| Moduł             | Odpowiedzialność                             |
| ----------------- | -------------------------------------------- |
| `main.py`         | Integracja FastAPI/FastMCP i endpointy REST  |
| `data/`           | Modele, magazyn, konto i historia transakcji |
| `mcp_tools.py`    | Publiczna logika biznesowa A2A               |
| `internal_ops.py` | Komunikacja z Producentem                    |

---

## ⚙️ Główne funkcje

### `data/models.py`

Zawiera modele Pydantic:

* **`Item`** — produkt (`name`, `quantity`, `unit`, `price`),
* **`TradeMessage`** — koperta komunikacyjna A2A zawierająca nadawcę, odbiorcę, typ komunikatu, produkt i dane transakcji.

Obsługiwane komunikaty:

```text
CALL_FOR_PROPOSAL
PROPOSAL
ACCEPT_PROPOSAL
REJECT_PROPOSAL
AVAILABILITY_REQUEST
AVAILABILITY_RESPONSE
DELIVERY
```

### `data/sql_functions.py`

Warstwa dostępu do SQLite odpowiedzialna za:

* inicjalizację bazy i danych początkowych,
* zarządzanie stanem magazynowym,
* obsługę salda hurtowni,
* rejestrowanie transakcji,
* pobieranie historii operacji.

Domyślne saldo początkowe: **10 000 PLN**.

### `handlers/mcp_tools.py`

Publiczne narzędzia dostępne dla agentów:

| Narzędzie                   | Funkcja                                 |
| --------------------------- | --------------------------------------- |
| `get_balance()`             | Pobiera saldo hurtowni                  |
| `get_transaction_history()` | Pobiera historię transakcji             |
| `check_availability(...)`   | Sprawdza dostępność produktu            |
| `request_offer(...)`        | Obsługuje `CALL_FOR_PROPOSAL`           |
| `accept_offer(...)`         | Realizuje sprzedaż po `ACCEPT_PROPOSAL` |
| `receive_delivery(...)`     | Przyjmuje dostawę od Producenta         |

### `handlers/internal_ops.py`

Wewnętrzna komunikacja z Producentem:

* `request_offer(...)` — wysyła `CALL_FOR_PROPOSAL`,
* `accept_offer(...)` — wysyła `ACCEPT_PROPOSAL` i obsługuje `DELIVERY`.

---

## 🌐 REST API

| Metoda | Endpoint                 | Opis                                 |
| ------ | ------------------------ | ------------------------------------ |
| `GET`  | `/products`              | Katalog produktów i stany magazynowe |
| `GET`  | `/finance/balance`       | Aktualne saldo                       |
| `GET`  | `/finance/transactions`  | Historia transakcji                  |
| `POST` | `/a2a/message`           | Obsługa komunikatów A2A              |
| `POST` | `/a2a/buy/request-offer` | Zapytanie ofertowe do Producenta     |
| `POST` | `/a2a/buy/accept-offer`  | Akceptacja oferty Producenta         |

### FastMCP

Narzędzia agentowe są dostępne przez endpoint:

```text
/mcp
```

Transport: **SSE (Server-Sent Events)**.

---

## 📑 Protokół A2A / CNP

| Zdarzenie               | Otrzymany komunikat    | Odpowiedź                               |
| ----------------------- | ---------------------- | --------------------------------------- |
| Sprawdzenie dostępności | `AVAILABILITY_REQUEST` | `AVAILABILITY_RESPONSE`                 |
| Zapytanie ofertowe      | `CALL_FOR_PROPOSAL`    | `PROPOSAL` / `REJECT_PROPOSAL`          |
| Akceptacja oferty       | `ACCEPT_PROPOSAL`      | `ACCEPT_PROPOSAL` / `REJECT_PROPOSAL`   |
| Odrzucenie oferty       | `REJECT_PROPOSAL`      | `REJECTED`                              |
| Przyjęcie dostawy       | `DELIVERY`             | `DELIVERY_RECEIVED` / `DELIVERY_FAILED` |

---

## 🔄 Przepływ transakcji

### Sprzedaż klientowi

```text
Klient (R1)                         Warehouse (H1)
    │                                      │
    │──── CALL_FOR_PROPOSAL ─────────────►│
    │◄────────── PROPOSAL ────────────────│
    │                                      │
    │──── ACCEPT_PROPOSAL ───────────────►│
    │                                      │
    │                         stock -= quantity
    │                         balance += total_cost
    │                         + SALE
    │                                      │
    │◄──── ACCEPT_PROPOSAL (Ack) ─────────│
```

### Zakup od Producenta

```text
Warehouse (H1)                    Producent (F1)
      │                                  │
      │──── CALL_FOR_PROPOSAL ─────────►│
      │◄────────── PROPOSAL ────────────│
      │                                  │
      │──── ACCEPT_PROPOSAL ───────────►│
      │◄────────── DELIVERY ────────────│
      │                                  │
      │  balance -= total_cost           │
      │  stock += quantity                │
      │  + PROCUREMENT_PAYMENT            │
```

---

## 💰 Model finansowy

Każda transakcja wpływa na saldo i jest zapisywana w historii:

```text
Sprzedaż              → balance += total_cost
Zakup od Producenta   → balance -= total_cost
```

System sprawdza:

* dostępność produktu przed sprzedażą,
* wystarczające środki przed zakupem,
* poprawność aktualizacji magazynu i finansów.

