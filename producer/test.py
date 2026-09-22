import asyncio
from fastmcp import Client


async def test_mcp_server():
    # Połączenie z uruchomionym serwerem - upewnij się, że port się zgadza
    async with Client("http://127.0.0.1:8001/sse") as client:
        print("--- Test: check_availability ---")
        avail = await client.call_tool(
            "check_availability",
            arguments={
                "sender_id": "H1",
                "receiver_id": "P1",
                "item_name": "flour",
                "quantity": 25.0
            }
        )
        print(avail)

        print("\n--- Test: request_offer ---")
        offer = await client.call_tool(
            "request_offer",
            arguments={
                "sender_id": "H1",
                "receiver_id": "P1",
                "item_name": "flour",
                "quantity": 25.0
            }
        )
        print(offer)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())