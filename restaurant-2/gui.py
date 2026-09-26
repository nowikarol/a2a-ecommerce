import streamlit as st
import requests

st.set_page_config(page_title="Restauracja 2 - Panel", page_icon="🍕", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    [data-testid="stAppViewContainer"] { overflow-y: hidden !important; }
    </style>
""", unsafe_allow_html=True)

API_URL_CHAT = "http://127.0.0.1:8022/chat"
API_URL_POWIADOMIENIA = "http://127.0.0.1:8022/powiadomienia"

# Inicjalizacja stanu
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Witaj Szefie! System zaopatrzenia gotowy. Co robimy?"}]

st.title("🍕 Restauracja nr 2 - Panel Dowodzenia")
st.subheader("💬 Czat z Agentem Zaopatrzeniowym")

# kontener na czat o stałej wysokości
chat_box = st.container(height=300)

def renderuj_wiadomosci():
    """Rysuje dokładnie jeden zestaw wiadomości wewnątrz kontenera."""
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

# Ciche odpytywanie endpointu w tle co 5 sekund bez resetowania całej strony
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

# Uruchomienie sprawdzania tła
sprawdz_tlo()

# Wyrysowanie historii
renderuj_wiadomosci()

# Obsługa wejścia użytkownika w jednym, synchronicznym przebiegu
if polecenie := st.chat_input("Napisz polecenie, np. 'Przygotuj pizzę...'"):
    # 1. Dodajemy wiadomość użytkownika i natychmiast ją rysujemy
    st.session_state.messages.append({"role": "user", "content": polecenie})
    with chat_box:
        with st.chat_message("user"):
            st.markdown(polecenie)

        # 2. Rysujemy odpowiedź asystenta w tym samym kontenerze
        with st.chat_message("assistant"):
            with st.spinner("Agent analizuje rynek i podejmuje decyzje..."):
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