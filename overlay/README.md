# 🌐 A2A Supply Chain Visualizer (Nakładka Grafowa)

Autonomiczna nakładka webowa wizualizująca w czasie rzeczywistym węzły handlowe (**Producent P1, Hurtownie H1 i H2, Restauracje R1 i R2**) oraz przesyłane między nimi komunikaty JSON w protokołach **MCP (Model Context Protocol)** i **CNP (Contract Net Protocol)**.

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

## 🎨 Główne Funkcjonalności

1. **Graf Sieci w Czasie Rzeczywistym (SVG):**
   * **Węzły:**
     * 🏭 **P1 (Producent)** – port 8001
     * 🏢 **H1 (Hurtownia 1)** – port 8004
     * 🏬 **H2 (Hurtownia 2)** – port 8005
     * 🍕 **R1 (Restauracja 1)** – port 8002
     * 🍝 **R2 (Restauracja 2)** – port 8022 / 8003
   * **Połączenia (Krawędzie):**
     * P1 ↔ H1, P1 ↔ H2
     * H1 ↔ R1, H1 ↔ R2
     * H2 ↔ R1, H2 ↔ R2
   * **Lecące Pakiety i Piktogramy:**
     * Gdy wysyłany jest komunikat, piktogram z opisem surowca i ilości płynnie leci po krzywej wzdłuż krawędzi od nadawcy do odbiorcy.
     * Kodowanie kolorystyczne i piktogramy:
       * 🔍 **AVAILABILITY_REQUEST / RESPONSE** – cyjan
       * 📑 **CALL_FOR_PROPOSAL** – pomarańczowy
       * 🏷️ **PROPOSAL** – złoty / bursztynowy
       * 🤝 **ACCEPT_PROPOSAL** – zielony
       * ❌ **REJECT_PROPOSAL** – czerwony
       * 🚚 **DELIVERY** – fioletowy
     * Dotarcie pakietu wywołuje falę uderzeniową (efekt ripple) oraz subtelny dźwięk syntetyzowany przez Web Audio API.

2. **Podgląd i Inspekcja JSON:**
   * Kliknięcie w dowolny przelatujący pakiet lub pozycję na pasku bocznym otwiera modal z pełnym, sformatowanym dokumentem JSON zgodnym ze schematami `docs/schemas/json-schemas/`.
   * Przycisk szybkiego kopiowania JSON do schowka.

3. **Interaktywne Sterowanie z Poziomu Nakładki:**
   * **⚡ Pełny Cykl CNP (Demo):** Automatyczna demonstracja 5-etapowego protokołu handlowego (zapytanie o dostępność, oferty, wybór najtańszego, zamówienie u producenta i dostawa).
   * **🍕 R1: Gotuj pizzę:** Wywołuje przygotowanie pizzy w R1, co zużywa składniki i wyzwala automatyczne przetargi w hurtowniach.
   * **🔍 R1: Audyt:** Wywołuje natychmiastowy audyt spiżarni R1 i zapytania przetargowe.
   * **🌾 H1: Kup u P1:** Wywołuje zamówienie mąki przez Hurtownię H1 u Producenta P1.
   * **💬 Konsola Czat:** Umożliwia wysłanie dowolnego polecenia w języku naturalnym do agenta R1, R2 lub H1.

4. **Monitoring Baz Danych i Portfeli:**
   * Dolny pasek na żywo prezentuje saldo portfela (PLN) oraz stan katalogów/magazynów w SQLite.
   * Kliknięcie na węzeł (np. R1, H1) otwiera szczegółową tabelę ze stanem surowców, cenami i historią transakcji.

---

## 🔒 Bezpieczeństwo i Nienaruszalność Kodu

Nakładka działa jako całkowicie niezależna warstwa obserwacyjna (Sidecar Visualizer):
* Żadne istniejące pliki w katalogach `producer/`, `restaurant-1/`, `restaurant-2/`, `warehouse-1/`, `warehouse-2/` ani `docs/` nie zostały zmodyfikowane.
* Komunikacja opiera się na pasywnym monitorowaniu logów, bazy SQLite oraz oficjalnych interfejsach REST API.
