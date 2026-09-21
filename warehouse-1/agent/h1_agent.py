from dotenv import load_dotenv
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from agent.tools import get_warehouse_stock, check_balance, procure_product_from_producer

load_dotenv()

SYSTEM_PROMPT = """
Jesteś agentem handlowym zarządzającym Hurtownią H1.
Twoim celem jest obsługa zamówień i monitorowanie stanów magazynowych oraz finansów.

Zasady działania:
1. Sprawdzaj stan magazynowy przed składaniem obietnic.
2. Gdy poziom produktu spadnie poniżej 20 sztuk, automatycznie dozamawiaj go u Producenta (F1).
3. Przed dokonaniem zakupu zawsze sprawdzaj saldo portfela (check_balance).
4. Jeśli serwer producenta jest niedostępny, zgłoś błąd i poinformuj o aktualnym stanie magazynu.
"""

tools = [get_warehouse_stock, check_balance, procure_product_from_producer]

agent = create_agent(
    model="google_genai:gemini-3.1-flash-lite",
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=InMemorySaver()
)

def run_h1_agent(prompt: str, thread_id: str = "h1_default_session") -> str:
    config = {"configurable": {"thread_id": thread_id}}
    response = agent.invoke({"messages": [("user", prompt)]}, config=config)
    return response["messages"][-1].content