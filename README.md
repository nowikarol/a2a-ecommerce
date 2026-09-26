# A2A - Konfiguracja i uruchomienie projektu

## Wymagania wstępne

### Wersja Pythona: **3.12** 




Python 3.11 również powinien działać, ale środowisko było testowane i
potwierdzone na **3.12**.

Sprawdź dostępne wersje Pythona:

```
py --list
```

Jeśli nie masz 3.12, pobierz instalator z [python.org](https://www.python.org/downloads/)
i zainstaluj go **obok** innych wersji (nie musisz usuwać istniejących).

---

## 1. Tworzenie środowiska wirtualnego (venv)

Wszystkie zależności instalujemy w izolowanym `venv`, żeby nie
konfliktować z innymi projektami Pythona na tym samym komputerze —
mieszanie zależności z różnych projektów w jednym globalnym środowisku
było źródłem większości problemów podczas konfiguracji.

Z katalogu głównego repo (`A2A\`):

```
py -3.12 -m venv venv
```

### Aktywacja środowiska

**cmd.exe:**
```
venv\Scripts\activate
```

**PowerShell:**
```
.\venv\Scripts\Activate.ps1
```

Jeśli PowerShell zablokuje uruchamianie skryptów, wykonaj najpierw:
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Po aktywacji linia poleceń powinna mieć przedrostek `(venv)`. Zweryfikuj wersję:

```
python --version
```

Powinno pokazać `Python 3.12.x`.

**Pamiętaj:** za każdym razem, gdy otwierasz nowy terminal do pracy nad
projektem, musisz ponownie aktywować `venv` (nie zostaje aktywny
globalnie).

---

## 2. Instalacja zależności

Z aktywowanym `venv`:

```
pip install -r requirements.txt
```

Jeżeli pojawi się błąd `ResolutionImpossible` albo konflikty wersji,
sprawdź czy `venv` jest na pewno aktywny (`(venv)` w prompcie) i czy nie
instalujesz przypadkiem do globalnego Pythona.

### Znane pułapki w zależnościach

- **`mcp`** — trzymamy `<2.0.0`, bo wersja 2.x zmienia nazwę wyjątku
  `McpError` na `MCPError` (breaking change).
- **`fastmcp`** — trzymamy `<3.0.0` z tego samego powodu (świeży, duży
  release 3.x).
- **`langchain-google-genai`** — trzymamy `<3.0.0`. Wersja 4.x
  przechodzi na nowy, ujednolicony SDK `google-genai` zamiast starego
  `google-generativeai`, co wymagałoby zmian w kodzie.
- **Nie dodawaj ręcznie** `google-generativeai` ani
  `google-ai-generativelanguage` z konkretną wersją — `langchain-google-genai`
  sam dobiera kompatybilne wersje tych pakietów. Ręczne przypięcie ich
  osobno kończy się nierozwiązywalnym konfliktem wersji.

---

## 3. Konfiguracja kluczy API (`.env`)

Klucz pobierzesz z
[Google AI Studio](https://aistudio.google.com/apikey).

Przykładowa zawartość `.env` (bez cudzysłowów, bez spacji wokół `=`):

```
GOOGLE_API_KEY=twoj_klucz_tutaj
```





Dodaj `.env` do `.gitignore` w każdym module, żeby nie trafił
przypadkiem do repozytorium.

---

## 4. Uruchomienie serwerów

Adresy poszczególnych węzłów (do zweryfikowania/utrzymania w kodzie
klienta, np. w `NODE_ENDPOINTS`):

| Węzeł | Adres | Uwagi |
|---|---|---|
| P1 (Producent) | `http://localhost:8001/sse` | |
| R1 (Restauracja 1) | `http://localhost:8002/sse` | do potwierdzenia |
| R2 (Restauracja 2) | `http://localhost:8003/sse` | do potwierdzenia |
| H1 (Magazyn 1) | `http://127.0.0.1:8004/mcp/sse` | **nie** `/sse` — inna ścieżka niż pozostałe węzły, potwierdzone z README H1 |
| H2 (Magazyn 2) | `http://localhost:8005/sse` | |



### Uruchomienie wszystkich serwerów naraz

Użyj `start_all.bat` z katalogu głównego repo — otwiera 5 osobnych
okien terminala, po jednym na serwer (P1, R1, R2, H1, H2).

---



## Szybki start (skrót)

```
py -3.12 -m venv venv
venv\Scripts\activate          # lub .\venv\Scripts\Activate.ps1 w PowerShell
pip install -r requirements.txt
# utwórz .env oraz dodaj zmienna GOOGLE_API_KEY
start_all.bat
```