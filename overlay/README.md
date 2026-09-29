# 🌐 A2A Trade Flow Demonstrator (Nakładka Prezentacyjna)

Dedykowana nakładka webowa stworzona wyłącznie w celu **wizualizacji i demonstracji przebiegu handlu wieloagentowego** w łańcuchu dostaw (**Producent P1, Hurtownie H1 i H2, Restauracje R1 i R2**), w oparciu o oficjalny standard **Contract Net Protocol (CNP)** oraz **Model Context Protocol (MCP)**.

---

## 🚀 Jak uruchomić i otworzyć nakładkę?

1. **Adres w przeglądarce:**
   ```text
   http://localhost:8080
   ```
2. **Uruchomienie serwera nakładki:**
   * Poprzez skrypt wsadowy:
     ```cmd
     overlay\start_overlay.bat
     ```
   * Lub bezpośrednio z terminala:
     ```bash
     cd overlay
     python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
     ```

---

## 🎨 Wizja Artystyczna i Architektura Demonstratora

Nowa wersja nakładki została całkowicie przeprojektowana pod kątem **czystej, profesjonalnej demonstracji procesu handlowego**:
* **Usunięto rozpraszające elementy**: brak paneli czatu z promptami LLM, formularzy technicznych i surowych strumieni logów.
* **100% Focus na Procesie Handlu**: interfejs prezentuje dynamiczny graf relacji, 5-krokową oś czasu protokołu CNP, przystępną narrację biznesową każdego etapu oraz podgląd prawdziwych pakietów JSON.

---

## 🎬 4 Predefiniowane Scenariusze Demonstracyjne

U góry ekranu znajduje się pasek wyboru 4 kluczowych scenariuszy handlowych:

1. ⚡ **Scenariusz 1: Standardowy Cykl Handlu (CNP - Ścieżka Sukcesu)**
   * **Aktorzy:** Restauracja R1 (Kupujący) ➔ Hurtownie H1 i H2 (Sprzedawcy).
   * **Przebieg:** R1 weryfikuje dostępność 5 kg mąki, zbiera konkurencyjne oferty cenowe, wybiera najtańszą hurtownię (H1: 17.50 PLN vs H2: 20.00 PLN), stosuje **zasadę milczenia** wobec H2, zawiera kontrakt i odbiera dostawę z atomowym rozliczeniem w SQLite (ACID).

2. ❌ **Scenariusz 2: Odrzucenie i Automatyczny Fallback**
   * **Aktorzy:** Restauracja R1 ➔ H1 i H2.
   * **Przebieg:** R1 wybiera najtańszą ofertę w H1, lecz towar zostaje w międzyczasie wyprzedany przez innego klienta (**Race Condition**). Hurtownia H1 zwraca `REJECT_PROPOSAL`. Autonomiczny agent R1 nie przerywa pracy, lecz natychmiast uruchamia procedurę **Fallback** – zawiera kontrakt z kolejną hurtownią (H2: 20.00 PLN) i pomyślnie zaopatruje kuchnię.

3. 🌾 **Scenariusz 3: Dostawa Hurtowa od Producenta (B2B)**
   * **Aktorzy:** Hurtownia H1 (Kupujący) ➔ Producent P1 (Sprzedający).
   * **Przebieg:** Demonstracja rekurencji protokołu A2A (Hurtownia, która wcześniej była sprzedawcą, staje się kupującym). H1 zamawia partię 25 kg mąki po cenie fabrycznej (2.50 PLN/kg = 62.50 PLN) bezpośrednio w fabryce Producenta P1.

4. 👤 **Scenariusz 4: Decyzja Człowieka (Human-in-the-Loop - HITL)**
   * **Aktorzy:** Restauracja R2 (Kupujący) ➔ Hurtownie H1 i H2 ➔ Operator (Człowiek).
   * **Przebieg:** Demonstracja nadzorowanej sztucznej inteligencji. Agent R2 porównuje oferty na 10 kg sera Mozzarella, identyfikuje najtańszą ofertę w H1 (85.00 PLN vs 145.00 PLN w H2), lecz **wstrzymuje proces zakupu**. W interfejsie pojawia się interaktywny panel autoryzacji: dopiero gdy człowiek kliknie `[Zatwierdź zakup]`, agent finalizuje transakcję w SQLite.

---

## 🔄 5-Krokowa Oś Czasu Handlu (Stepper CNP)

Wizualizacja na bieżąco prezentuje postęp transakcji na osi czasu:
* **Krok 1: 🔍 Weryfikacja Dostępności** (`AVAILABILITY_REQUEST` / `RESPONSE`)
* **Krok 2: 🏷️ Zbieranie Ofert Cenowych** (`CALL_FOR_PROPOSAL` / `PROPOSAL`)
* **Krok 3: ⚖️ Wybór Najlepszej Oferty** (Algorytm `min(total_cost)` i zasada milczenia)
* **Krok 4: 🤝 Zawarcie Kontraktu / Decyzja** (`ACCEPT_PROPOSAL` / `REJECT_PROPOSAL` / `HITL`)
* **Krok 5: 🚚 Dostawa i Rozliczenie ACID** (`DELIVERY` oraz natychmiastowa aktualizacja sald i magazynów w SQLite)

---

## 🛠️ Panel Narracyjny i Inspektor JSON

Prawa strona ekranu zawiera:
* **Kartę Narracyjną:** Przystępne objaśnienie w języku polskim, co dokładnie robią agenci w bieżącym kroku, wzbogacone o pole **💡 Reguła Protokołu** (wyjaśniające logikę biznesową i inżynieryjną).
* **Inspektor JSON:** Podgląd rzeczywistej struktury przesyłanego pakietu danych (zgodnego ze schematami w `docs/schemas/json-schemas/`) wraz z przyciskiem kopiowania do schowka.
* **Dziennik Zdarzeń Sesji:** Chronologiczny wykaz zarejestrowanych etapów bieżącego pokazu.

---

## 📊 Live Monitoring Baz Danych i Portfeli

Na dolnym pasku na żywo prezentowane są:
* Salda portfeli (PLN) agentów
* Liczba pozycji magazynowych i stan spiżarni
* Po zrealizowaniu dostawy (Krok 5) kafelki węzłów ulegają podświetleniu (**flash update**), potwierdzając widzowi, że transakcja została realnie zaksięgowana w bazach danych SQLite projektu.
