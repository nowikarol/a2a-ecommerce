# Warehouse 1 (H1) — Agent API & MCP Server

System zarządzania Hurtownią **H1** oparty na **FastAPI**, **FastMCP (Model Context Protocol)** oraz **LangChain / LangGraph**.

System umożliwia:

* obsługę zamówień składanych przez Restauracje za pośrednictwem **MCP**,
* zarządzanie stanem magazynowym i finansami,
* autonomiczne monitorowanie zapasów przez Agenta H1,
* automatyczne uzupełnianie brakujących produktów u Producenta **F1**.

---

## 🏗️ Architektura

System składa się z trzech głównych warstw:

| Warstwa    | Technologia                           | Odpowiedzialność                                                   |
| ---------- | ------------------------------------- | ------------------------------------------------------------------ |
| REST API   | FastAPI                               | Komunikacja użytkownika z Agentem H1, endpoint `/chat`             |
| MCP Server | FastMCP + SSE                         | Udostępnianie narzędzi dla zewnętrznych agentów i klientów         |
| Agent H1   | LangChain / LangGraph + Google Gemini | Monitorowanie magazynu, finansów i realizacja zakupów u Producenta |

Serwer działa domyślnie na porcie **8004**.

---

## 📁 Struktura projektu

```text
warehouse1/
├── agent/
│   ├── h1_agent.py          # Konfiguracja i pętla wykonawcza Agenta H1
│   └── tools.py             # Narzędzia Agenta
├── data/
│   ├── models.py            # Modele Pydantic
│   └── sql_functions.py     # Operacje na bazie SQLite
├── network/
│   ├── client.py            # Klient HTTP do komunikacji z Producentem F1
│   └── server.py            # Serwer FastMCP
├── main.py                  # Punkt startowy aplikacji
├── requirements.txt         # Wymagane biblioteki
   
```

---

## 🔌 MCP Server

Serwer FastMCP udostępnia narzędzia dla zewnętrznych klientów i agentów, np. Restauracji **R2**.

Endpoint:

```text
http://127.0.0.1:8004/mcp/sse
```

### Dostępne narzędzia

| Narzędzie            | Opis                                                                                                             |
| -------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `check_availability` | Sprawdza dostępność produktu i jego aktualny stan magazynowy.                                                    |
| `request_offer`      | Przygotowuje ofertę cenową na podstawie cennika H1. Odrzuca zapytanie, jeśli produktu nie ma w wymaganej ilości. |
| `accept_offer`       | Finalizuje sprzedaż, aktualizuje stan magazynowy i zwiększa saldo H1.                                            |

---

## 🤖 Agent H1

Agent H1 wykorzystuje **LangChain / LangGraph** oraz model **Google Gemini** do autonomicznego zarządzania procesami hurtowni.

### Narzędzia Agenta

| Narzędzie                       | Opis                                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `get_warehouse_stock`           | Pobiera listę produktów wraz z ilością i ceną.                                                                      |
| `check_balance`                 | Sprawdza aktualne saldo finansowe H1.                                                                               |
| `procure_product_from_producer` | Realizuje zakup produktu od Producenta F1: pobiera ofertę, sprawdza środki, akceptuje ofertę i księguje transakcję. |

---

## 🔄 Przepływ zamówienia

### Restauracja → H1

```text
Restauracja R2
      │
      ▼
check_availability
      │
      ▼
request_offer
      │
      ▼
   Oferta H1
      │
      ▼
accept_offer
      │
      ▼
Sprzedaż + aktualizacja magazynu + księgowanie
```

### H1 → Producent F1

```text
Agent H1
   │
   ▼
request_offer
   │
   ▼
Oferta Producenta
   │
   ▼
Sprawdzenie środków
   │
   ▼
accept_offer
   │
   ▼
Dostawa + aktualizacja magazynu + księgowanie
```
