from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from agent.tools import (
    get_warehouse_stock,
    check_balance,
    check_producer_stock,
    get_producer_proposal,
    finalize_producer_purchase
)

load_dotenv()

SYSTEM_PROMPT = """
Jesteś agentem handlowym zarządzającym Hurtownią H1.
Twoim celem jest obsługa zapytań o stan magazynowy i finanse oraz odpowiedzialne dokonywanie zakupów surowców u Producenta.

Główny zakres obowiązków:
1. Pytania o stan i finanse: Używaj `get_warehouse_stock` oraz `check_balance`.
2. Dozamawianie towaru u Producenta: Kiedy musisz dokupić surowiec, BEZWZGLĘDNIE wykonuj 5-etapowy protokół CNP:
   - KROK1 1: Wywołaj `check_producer_stock`, aby sprawdzić dostępność u Producenta.
   - KROK2 2: Wywołaj `get_producer_proposal`, aby pobrać oficjalną wycenę (`unit_price` i `total_cost`).
   - KROK3 3: Użyj `check_balance` i zweryfikuj czy stan konta pozwala na zakup.
   - KROK4 4: Wywołaj `finalize_producer_purchase` przekazując wynegocjowane parametry.
   - KROK5 5: Dostawa zostanie zarejestrowana po udanej transakcji. Poinformuj użytkownika o wyniku.

Zasady działania:
- Gdy poziom produktu w magazynie spadnie poniżej 20 sztuk, zaproponuj lub wykonaj jego dozamówienie u Producenta.
- Przed dokonaniem zakupu zawsze weryfikuj saldo portfela.
"""

tools = [
    get_warehouse_stock,
    check_balance,
    check_producer_stock,
    get_producer_proposal,
    finalize_producer_purchase
]

agent = create_agent(
    model="google_genai:gemini-3.1-flash-lite",
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver()
)


async def run_h1_agent(prompt: str, thread_id: str = "h1_default_session") -> str:
    config = {"configurable": {"thread_id": thread_id}}
    res = await agent.ainvoke({"messages": [("user", prompt)]}, config=config)
    return res.get("messages", [])[-1].content