# Warehouse 1 (H1) — Agent API & MCP Server

**H1** to autonomiczny agent zarządzający hurtownią w systemie e-commerce opartym na komunikacji **A2A (Agent-to-Agent)**.

System łączy **FastAPI**, **FastMCP**, **LangChain / LangGraph** oraz **Google Gemini** i odpowiada zarówno za obsługę zamówień od restauracji, jak i za monitorowanie magazynu oraz automatyczne uzupełnianie zapasów u Producenta **P1**.

### Główne zadania H1

* obsługa zamówień restauracji przez **MCP** z wykorzystaniem **Contract Net Protocol (CNP)**,
* zarządzanie stanem magazynowym i finansami w bazie **SQLite**,
* monitorowanie poziomu zapasów i wykrywanie produktów poniżej `min_threshold`,
* autonomiczne składanie zamówień u Producenta **P1**,
* realizacja i księgowanie sprzedaży oraz zakupów.

---

## 🏗️ Architektura

System składa się z trzech głównych elementów:

| Element        | Technologia                    | Odpowiedzialność                                           |
| -------------- | ------------------------------ | ---------------------------------------------------------- |
| **REST API**   | FastAPI                        | Interfejs użytkownika i komunikacja z Agentem (`/chat`)    |
| **MCP Server** | FastMCP + SSE                  | Udostępnianie narzędzi B2B zewnętrznym agentom restauracji |
| **Agent H1**   | LangChain / LangGraph + Gemini | Monitorowanie hurtowni i autonomiczna realizacja zakupów   |

Dane operacyjne przechowywane są w relacyjnej bazie **SQLite**.

Serwer działa domyślnie na porcie **8004**.

---

## 📁 Struktura projektu

```text
warehouse1/
├── agent/
│   ├── h1_agent.py          # Konfiguracja i pętla wykonawcza Agenta H1
│   └── tools.py             # Narzędzia wykorzystywane przez Agenta
│
├── data/
│   ├── models.py            # Modele Pydantic i walidacja komunikatów
│   └── sql_functions.py     # Operacje na bazie SQLite
│
├── network/
│   ├── client.py            # Komunikacja z Producentem P1
│   └── server.py            # Serwer FastMCP i narzędzia B2B
│
├── main.py                  # Punkt startowy aplikacji
└── requirements.txt         # Zależności projektu
```

---

## 🔌 MCP Server

**FastMCP** udostępnia funkcje handlowe jako narzędzia MCP dostępne dla zewnętrznych agentów restauracji, np. **R1** i **R2**.

### Endpoint

```text
http://127.0.0.1:8004/mcp/sse
```

### Narzędzia B2B

| Narzędzie            | Opis                                                                           |
| -------------------- | ------------------------------------------------------------------------------ |
| `check_availability` | Sprawdza dostępność produktu i aktualny stan magazynowy.                       |
| `request_offer`      | Przygotowuje ofertę cenową (`PROPOSAL`) na podstawie danych H1.                |
| `accept_offer`       | Akceptuje ofertę, realizuje sprzedaż, aktualizuje magazyn i księguje przychód. |
| `receive_delivery`   | Obsługuje dostawę od Producenta P1 i rozlicza zakup.                           |

Narzędzia sprzedażowe realizują kolejne etapy **Contract Net Protocol (CNP)** pomiędzy restauracją a hurtownią.

---

## 🤖 Agent H1

Agent H1 działa autonomicznie w oparciu o **LangChain / LangGraph** oraz model **Google Gemini**.

Jego zadaniem jest monitorowanie sytuacji hurtowni i podejmowanie działań związanych z uzupełnianiem zapasów.

### Narzędzia Agenta

| Narzędzie                    | Opis                                                      |
| ---------------------------- | --------------------------------------------------------- |
| `get_warehouse_stock`        | Pobiera aktualny stan magazynu H1.                        |
| `get_low_stock_items`        | Wyszukuje produkty poniżej określonego `min_threshold`.   |
| `check_balance`              | Sprawdza aktualne saldo finansowe H1.                     |
| `check_producer_stock`       | Sprawdza dostępność produktu u Producenta P1.             |
| `get_producer_proposal`      | Pobiera ofertę cenową od Producenta P1.                   |
| `finalize_producer_purchase` | Sprawdza dostępne środki i finalizuje zakup u Producenta. |

Agent wykonuje również **audyt startowy**, dzięki któremu może wykryć braki w magazynie już podczas uruchamiania systemu.

---

## Przepływ zamówień

### Restauracja → H1

Proces sprzedaży wykorzystuje **Contract Net Protocol**:

```text
Restauracja
    │
    ▼
check_availability
    │
    ▼
request_offer
    │
    ▼
PROPOSAL
    │
    ▼
accept_offer
    │
    ▼
Sprzedaż
    │
    ├── aktualizacja magazynu
    ├── księgowanie przychodu
    └── asynchroniczne powiadomienie restauracji
```

Powiadomienie o dostawie jest uruchamiane asynchronicznie w tle, dzięki czemu proces sprzedaży nie zostaje zablokowany przez komunikację zwrotną.

### H1 → Producent P1

Agent automatycznie uzupełnia zapasy, gdy wykryje produkty poniżej wymaganego poziomu:

```text
Audyt / wykrycie niskiego stanu
              │
              ▼
   check_producer_stock
              │
              ▼
    get_producer_proposal
              │
              ▼
        check_balance
              │
              ▼
 finalize_producer_purchase
              │
              ▼
       Dostawa do H1
              │
              ▼
 Aktualizacja magazynu i finansów
```

---

## Dane i finanse

Hurtownia wykorzystuje **SQLite** do przechowywania danych operacyjnych, w szczególności:

* produktów i stanów magazynowych,
* progów `min_threshold`,
* cen,
* salda H1,
* historii transakcji.

Każda sprzedaż i każdy zakup są odpowiednio odzwierciedlane w stanie magazynu oraz finansach hurtowni.

---

## 🌐 Dostępne interfejsy

| Interfejs      | Adres        | Przeznaczenie                       |
| -------------- | ------------ | ----------------------------------- |
| **Swagger UI** | `/docs`      | Dokumentacja i testowanie REST API  |
| **Agent Chat** | `POST /chat` | Komunikacja z Agentem H1            |
| **MCP / SSE**  | `/mcp/sse`   | Komunikacja z zewnętrznymi agentami |

Przy uruchomieniu lokalnym:

```text
Swagger:  http://127.0.0.1:8004/docs
MCP:      http://127.0.0.1:8004/mcp/sse
```

---

