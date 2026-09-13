import json
import os
import subprocess
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastmcp import Client
from google import genai
from google.genai import types
from pydantic import BaseModel
from pyngrok import ngrok
import uvicorn

load_dotenv()

app = FastAPI(title="Factory A2A Agent - Supplier F1")

# 1. Nowa generacja SDK Gemini (google-genai)
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

SYSTEM_PROMPT = """
Jesteś autonomicznym Agentem Sprzedaży Fabryki (ID: F1).
Obsługujesz zapytania A2A i generujesz odpowiedzi cenowe.

ZASADY BIZNESOWE:
1. Domyślnie trzymaj się ceny katalogowej przekazanej z MCP.
2. Jeśli odbiorca (sender_id) to stały klient (np. R1), możesz przyznać 10% rabatu od ceny z MCP.
3. Wygeneruj WYŁĄCZNIE czysty JSON w jednym z formatów: PROPOSAL lub REJECT_PROPOSAL.
"""

# Wewnętrzny adres serwera MCP (działa na porcie 8000)
MCP_SERVER_URL = "http://0.0.0.0:8000/sse"


# 2. Definicja struktur JSON dla FastAPI
class ItemRequest(BaseModel):
    name: str
    quantity: int


class A2AMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: str
    item: ItemRequest


# 3. Endpoint A2A do odbierania wiadomości handlowych
@app.post("/a2a/rfq")
async def handle_rfq(msg: A2AMessage):
    if msg.message_type != "CALL_FOR_PROPOSAL":
        raise HTTPException(
            status_code=400, detail="Nieobsługiwany typ wiadomości"
        )

    # A. Połączenie z serwerem MCP w celu pobrania wyceny z bazy danych
    async with Client(MCP_SERVER_URL) as mcp_client:
        mcp_response = await mcp_client.call_tool(
            "get_preliminary_price",
            arguments={
                "product_code": msg.item.name,
                "quantity": msg.item.quantity,
                "sender_id": msg.receiver_id,
                "receiver_id": msg.sender_id,
            },
        )

    # B. Zbudowanie kontekstu dla LLM (Gemini)
    prompt_context = f"""
    PRZYCHODZĄCA WIADOMOŚĆ A2A:
    {msg.model_dump_json(indent=2)}

    DANE WYCENY Z MCP (DANE BAZOWE):
    {mcp_response}

    Przeanalizuj ofertę i wygeneruj odpowiedni JSON odpowiedzi A2A.
    """

    # C. Generowanie decyzji handlowej przez Gemini
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt_context,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    # D. Zwrócenie sparsowanego JSON
    return json.loads(response.text)

@app.get("/a2a/discovery")
async def get_agent_card():
    """Zwraca wizytówkę agenta i specyfikację komunikacji A2A."""
    return {
        "agent_id": "F1",
        "role": "Supplier Sales Agent",
        "capabilities": [
            "catalog_pricing",
            "stock_check",
            "autonomous_discount_negotiation",
        ],
        "interaction_rules": {
            "get_raw_prices": "Połącz się przez MCP do /sse i wywołaj get_preliminary_price",
            "negotiate_price": "Wyślij POST na /a2a/rfq z wiadomością CALL_FOR_PROPOSAL",
        },
    }
if __name__ == "__main__":
    PORT_MCP = 8000  # Port serwera MCP (FastMCP SSE)
    PORT_AGENT = 8001  # Port serwera Agenta FastAPI

    # 1. Czyszczenie starych procesów ngrok
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], capture_output=True)
    except Exception:
        pass

    ngrok.kill()

    # 2. Autoryzacja ngrok
    ngrok_key = os.getenv("NGROK_API_KEY") or os.getenv("NGROK_AUTHTOKEN")
    if ngrok_key:
        ngrok.set_auth_token(ngrok_key)

    # 3. Tworzenie tunelu ngrok dla serwera MCP (port 8000)
    tunnel = ngrok.connect(PORT_MCP)
    full_mcp_url = f"{tunnel.public_url}/sse"

    # Zapis adresu MCP do pliku dla skryptu bat
    with open("ngrok_url.txt", "w", encoding="utf-8") as f:
        f.write(full_mcp_url)

    # Kopiowanie do schowka Windows
    try:
        subprocess.run(["clip"], input=full_mcp_url.encode("utf-16"), check=True)
        clipboard_status = " [SKOPIOWANO DO SCHOWKA (CTRL+V)]"
    except Exception:
        clipboard_status = ""

    print("\n" + "=" * 70)
    print(" ADRES SERWERA MCP GOTOWY DLA KOLEGI:")
    print(f" {full_mcp_url}{clipboard_status}")
    print("=" * 70 + "\n")

    # POPRAWKA: Uruchomienie FastAPI na PORT_AGENT (8001), co zwalnia PORT_MCP (8000) dla mcp_server.py
    uvicorn.run(app, host="0.0.0.0", port=PORT_AGENT)