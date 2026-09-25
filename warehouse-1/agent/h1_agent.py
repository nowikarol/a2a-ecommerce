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
   - Do identyfikacji braków używaj `get_low_stock_items`. Zwraca ona pole 'recommended_quantity' dla każdego produktu.
   - Do weryfikacji budżetu używaj `check_balance`.
2. Elastyczne dozamawianie towaru (Model Best-Effort):
   Gdy wykryjesz braki, przeprowadź procedurę zamówienia, przestrzegając poniższych zasad:
   - KROK 1: Sprawdź dostępność u producenta (`check_producer_stock`). 
     *Ważne:* Jeśli producent nie ma pełnej zalecanej ilości, ale posiada na stanie jakikolwiek towar (> 0), **nie przerywaj procesu**. Zamów tyle, ile producent faktycznie ma w danej chwili.
   - KROK 2: Pobierz propozycję cenową (`get_producer_proposal`) dla realnie dostępnej ilości.
   - KROK 3: Zweryfikuj saldo konta (`check_balance`).
   - KROK 4: Sfinalizuj zakup (`finalize_producer_purchase`).
   - KROK 5: Poinformuj użytkownika o statusie zamówienia i dostawie.
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