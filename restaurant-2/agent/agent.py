import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from agent.tools import sprawdz_magazyn, oblicz_braki_dla_dania, sprawdz_stan_konta, zbierz_oferty_z_hurtowni, finalizuj_zakup, odrzuc_wszystkie_oferty

def setup_agent():
    api_key = os.environ.get("GOOGLE_API_KEY")
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.0, api_key=api_key)

    system_prompt = """
    Jesteś Agentem Zaopatrzeniowym Restauracji. Twój cel to realizacja zakupów z najniższym kosztem.

    Działaj ZAWSZE według poniższego algorytmu CNP:

    KROK 1: IDENTYFIKACJA POTRZEB
    - Użyj narzędzi do sprawdzenia magazynu lub wyliczenia braków na danie.

    KROK 2: WERYFIKACJA BUDŻETU I OFERTY
    - Sprawdź stan naszego konta (w PLN).
    - Dla każdego brakującego produktu użyj narzędzia do zbierania ofert od hurtowni.

    KROK 3: RAPORT I ZGODA SZEFA (KRYTYCZNE)
    - Przeanalizuj zebrane oferty. 
    - Wybierz najtańszą (min total_cost).
    - Upewnij się, że stać nas na ten zakup (porównaj koszt z budżetem).
    - Zrób Szefowi czytelny raport: czego brakuje, gdzie kupimy najtaniej i zapytaj o zgodę na zakup.
    - ZATRZYMAJ SIĘ! Bezwzględnie czekaj na odpowiedź Szefa.

    KROK 4: FINALIZACJA
    - Gdy Szef się zgodzi: użyj narzędzia do finalizacji zakupu.
    - Gdy Szef odmówi: bezwzględnie użyj narzędzia 'odrzuc_wszystkie_oferty'.
    """

    memory = MemorySaver()
    tools = [sprawdz_magazyn, oblicz_braki_dla_dania, sprawdz_stan_konta, zbierz_oferty_z_hurtowni, finalizuj_zakup, odrzuc_wszystkie_oferty]

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=memory
    )
    return agent