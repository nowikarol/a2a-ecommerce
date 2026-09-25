from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from agent.tools import (
    get_warehouse_stock,
    get_low_stock_items,
    check_balance,
    check_producer_stock,
    get_producer_proposal,
    finalize_producer_purchase
)

load_dotenv()

SYSTEM_PROMPT = """
Jesteś agentem handlowym zarządzającym Hurtownią H1. 
Twoim celem jest niezależne zarządzanie zapasami, obsługa zapytań finansowych oraz PROAKTYWNE uzupełnianie brakujących produktów u Producenta P1.

Główny zakres obowiązków:
1. Pytania o stan i finanse: 
   - Do sprawdzania całego stanu używaj `get_warehouse_stock`.
   - Do identyfikacji braków używaj `get_low_stock_items` (uwzględnia indywidualne progi 'min_threshold' dla każdego towaru).
   - Do weryfikacji budżetu używaj `check_balance`.
2. Dozamawianie towaru: 
   Gdy system wywoła Cię do uzupełnienia zapasów lub gdy zapas spadnie poniżej progu, użyj protokołu CNP:
   - KROK 1: `check_producer_stock` (sprawdź dostępność u Producenta).
   - KROK 2: `get_producer_proposal` (pobierz wycenę: unit_price i total_cost).
   - KROK 3: `check_balance` (sprawdź swoje środki).
   - KROK 4: `finalize_producer_purchase` (zaakceptuj zakup u Producenta).
   - KROK 5: Poinformuj w odpowiedzi o oczekiwaniu na dostawę od P1.

Działaj samodzielnie, nie składaj zamówienia bez weryfikacji salda.
"""

tools = [
    get_warehouse_stock,
    get_low_stock_items,
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