import os
import json
import logging
from typing import Any, Dict
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()
logger = logging.getLogger("H2_CLIENT")
PRODUCER_URL = os.getenv("PRODUCER_URL","http://127.0.0.1:8001/sse")
PRODUCER_ID = "P1"
BUYER_ID = "H2"
async def call_producer_tool(tool_name: str,arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        async with sse_client(PRODUCER_URL) as (read_stream,write_stream):
            async with ClientSession(read_stream,write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name,arguments=arguments)
                if not result.content:
                    return  "No P1 answer"
                raw_text = result.content[0].text
                if isinstance(raw_text, str):
                    return json.loads(raw_text)
                return raw_text
    except Exception as e:
        logger.error(f"H2 cannot connect to ({tool_name}): {e}")

        return str(e)


async def check_producer_availability(item_name:str,quantity: int) -> Dict[str, Any]:
    '''
    Call check availability from producer
    '''
    return await call_producer_tool(
        "check_availability",
        {"item_name": item_name,
            "quantity": quantity,
            "sender_id": BUYER_ID,
            "receiver_id": PRODUCER_ID})



async def request_producer_proposal(item_name: str,quantity: int) -> Dict[str, Any]:
    '''
    Call a request from producer
    '''
    return await call_producer_tool(
        "request_offer",{
            "sender_id": BUYER_ID,
            "receiver_id": PRODUCER_ID,
            "item_name": item_name,
            "quantity": quantity})



async def accept_producer_proposal(item_name: str,quantity: int,price: float,total_cost: float) -> Dict[str, Any]:
    '''
    Call accept offer from producer
    '''
    return await call_producer_tool("accept_offer",{
            "sender_id": BUYER_ID,
            "receiver_id": PRODUCER_ID,
            "item_name": item_name,
            "quantity": quantity,
            "price": price,
            "total_cost": total_cost})