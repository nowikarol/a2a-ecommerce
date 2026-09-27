import streamlit as st
import requests
import sqlite3
import os

st.set_page_config(page_title="Restauracja 2 - Panel", page_icon="🍕", layout="wide")

# ==========================================
# WSTRZYKNIĘCIE CSS DLA NOWOCZESNEGO WYGLĄDU
# ==========================================
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    [data-testid="stAppViewContainer"] { overflow-y: hidden !important; }
    
    /* Stylizacja Karty Konta */
    .metric-card {
        background-color: #0f172a; 
        border: 1px solid #1e293b; 
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }
    .metric-label {
        font-size: 11px;
        font-weight: 600;
        color: #94a3b8; 
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 34px;
        font-weight: 900;
        color: #34d399;
        letter-spacing: -0.02em;
    }

    /* Stylizacja Siatki Magazynu */
    .inventory-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
        gap: 12px;
        align-content: start;
        margin-bottom: 24px;
    }
    .inv-card {
        background-color: rgba(15, 23, 42, 0.6); 
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 12px;
        height: 90px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        transition: border-color 0.2s;
    }
    .inv-card:hover {
        border-color: #3b82f6;
    }
    .inv-name {
        font-size: 13px;
        color: #94a3b8;
        margin-bottom: 4px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .inv-bottom {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
    }
    .inv-qty {
        font-size: 18px;
        font-weight: 700;
        color: #f8fafc;
    }
    .inv-unit {
        font-size: 11px;
        font-weight: 400;
        color: #64748b;
        margin-left: 2px;
    }
    .inv-status {
        font-size: 12px;
        padding: 2px 6px;
        border-radius: 6px;
        background: rgba(255,255,255,0.05);
    }
    .status-ok { border: 1px solid rgba(16, 185, 129, 0.3); background: rgba(16, 185, 129, 0.1); }
    .status-alert { border: 1px solid rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.1); }

    /* Stylizacja Siatki Menu */
    .menu-grid {
        display: grid;
        grid-template-columns: 1fr; /* Jedna kolumna ze względu na węższe okno */
        gap: 12px;
        align-content: start;
    }
    .menu-card {
        background-color: rgba(15, 23, 42, 0.4); 
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 14px;
        display: flex;
        flex-direction: column;
    }
    .menu-title {
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .title-amber { color: #fbbf24; }
    .title-emerald { color: #34d399; }
    .menu-desc {
        font-size: 11px;
        color: #94a3b8;
        line-height: 1.4;
    }
    </style>
""", unsafe_allow_html=True)

API_URL_CHAT = "http://127.0.0.1:8022/chat"
API_URL_POWIADOMIENIA = "http://127.0.0.1:8022/powiadomienia"

# --- ŚCIEŻKA DO BAZY DANYCH ---
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "restauracja_2.db")
if not os.path.exists(DB_PATH):
    DB_PATH = "data/restauracja_2.db"

# Inicjalizacja stanu
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Witaj Szefie! System zaopatrzenia gotowy. Co robimy?"}]

st.title("🍕 Restauracja nr 2 - Panel Dowodzenia")

# ==========================================
# PODZIAŁ EKRANU NA 3 KOLUMNY (30% | 40% | 30%)
# ==========================================
col1, col2, col3 = st.columns([3, 4, 3])

# --- LEWA KOLUMNA: CZAT ---
with col1:
    st.subheader("💬 Czat z Agentem")
    chat_box = st.container(height=400) 

def renderuj_wiadomosci():
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

# --- ŚRODKOWA KOLUMNA: MAGAZYN I KONTO ---
with col2:
    st.subheader("📦 Magazyn i Konto")
    magazyn_box = st.container(height=490)

# --- PRAWA KOLUMNA: MENU ---
with col3:
    st.subheader("📜 Menu")
    menu_box = st.container(height=490)

# Funkcja pobierająca z bazy wszystko na raz
@st.fragment(run_every=5)
def panel_danych():
    try:
        with sqlite3.connect(DB_PATH, timeout=1.0) as conn:
            # 1. Pobieranie danych konta i magazynu
            bal = conn.execute("SELECT balans FROM konto WHERE id = 1").fetchone()
            items = conn.execute("SELECT nazwa_produktu, ilosc, jednostka, prog_bezpieczenstwa FROM magazyn").fetchall()
            
            # 2. Bezpieczne pobieranie menu (nawet jeśli brakuje kolumny 'opis')
            menu_items = []
            menu_items = conn.execute("SELECT nazwa_dania FROM przepisy").fetchall()
                
        stan_konta = bal[0] if bal else 0.0

        # --- Renderowanie Magazynu (Środkowa Kolumna) ---
        with magazyn_box:
            # Karta Konta
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Stan Konta</div>
                    <div class="metric-value">{stan_konta:.2f} PLN</div>
                </div>
            """, unsafe_allow_html=True)
            
            # Siatka Magazynu (bez spacji na początku dla parsera HTML)
            st.markdown("#### 🍅 Zapasy:")
            if items:
                grid_html = '<div class="inventory-grid">'
                for item in items:
                    nazwa, ilosc, jedn, prog = item
                    
                    if ilosc < prog:
                        status_class = "status-alert"
                        status_icon = "⚠️"
                        qty_color = "#ff4b4b"
                    else:
                        status_class = "status-ok"
                        status_icon = "✅"
                        qty_color = "#f8fafc"
                    
                    grid_html += f'<div class="inv-card"><div class="inv-name">{nazwa}</div><div class="inv-bottom"><div><span class="inv-qty" style="color: {qty_color};">{ilosc}</span><span class="inv-unit">{jedn}</span></div><div class="inv-status {status_class}">{status_icon}</div></div></div>'
                    
                grid_html += '</div>'
                st.markdown(grid_html, unsafe_allow_html=True)
            else:
                st.info("Brak produktów w magazynie.")

        # --- Renderowanie Menu (Prawa Kolumna) ---
        with menu_box:
            if menu_items:
                menu_html = '<div class="menu-grid">'
                for danie in menu_items:
                    nazwa = danie[0]
                    
                    # Kolorowanie tytułów: Szmaragdowy dla sałatek/desek, Bursztynowy dla pizz
                    if any(keyword in nazwa.lower() for keyword in ["insalata", "deska", "tagliere", "sałatka"]):
                        title_color = "title-emerald"
                    else:
                        title_color = "title-amber"
                        
                    menu_html += f'<div class="menu-card"><div class="menu-title {title_color}">{nazwa}</div></div>'
                
                menu_html += '</div>'
                st.markdown(menu_html, unsafe_allow_html=True)
            else:
                st.info("Brak zdefiniowanego menu w bazie danych.")
                
    except Exception as e:
        with magazyn_box:
            st.error("Oczekuję na inicjalizację bazy danych...")
        with menu_box:
            st.error("Brak połączenia z bazą.")

# Ciche odpytywanie endpointu w tle co 5 sekund
@st.fragment(run_every=5)
def sprawdz_tlo():
    try:
        resp = requests.get(API_URL_POWIADOMIENIA, timeout=2)
        if resp.status_code == 200:
            nowe = resp.json().get("nowe_wiadomosci", [])
            if nowe:
                for wiadomosc in nowe:
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": f"🔔 **KOMUNIKAT Z TŁA:**\n\n{wiadomosc}"
                    })
                st.rerun()
    except Exception:
        pass

# --- URUCHOMIENIE KOMPONENTÓW ---
panel_danych()
sprawdz_tlo()
renderuj_wiadomosci()

# --- OBSŁUGA POLECEŃ (Pole input zawsze pod czatem) ---
with col1:
    if polecenie := st.chat_input("Napisz polecenie, np. 'Przygotuj pizzę...'"):
        st.session_state.messages.append({"role": "user", "content": polecenie})
        
        with chat_box:
            with st.chat_message("user"):
                st.markdown(polecenie)

            with st.chat_message("assistant"):
                with st.spinner("Agent myśli..."):
                    try:
                        odpowiedz = requests.post(
                            API_URL_CHAT, 
                            json={"polecenie": polecenie}, 
                            timeout=120
                        )
                        if odpowiedz.status_code == 200:
                            dane = odpowiedz.json()
                            tekst = dane.get("odpowiedz", "Brak odpowiedzi.")
                            st.markdown(tekst)
                            st.session_state.messages.append({"role": "assistant", "content": tekst})
                            
                            if dane.get("watek_zresetowany"):
                                st.toast("Pamięć agenta zresetowana.", icon="🔄")
                        else:
                            blad = f"Błąd API: Status {odpowiedz.status_code}"
                            st.error(blad)
                            st.session_state.messages.append({"role": "assistant", "content": blad})
                    except requests.exceptions.ConnectionError:
                        blad = "Brak połączenia z serwerem R2."
                        st.error(blad)
                        st.session_state.messages.append({"role": "assistant", "content": blad})