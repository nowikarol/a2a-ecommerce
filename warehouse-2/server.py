from scheam import (Item, Delivery, Accept_Offer, Reject, 
                    Request_Offer, Response_Offer,Availability_Request, 
                    Availability_Response)
from fastmcp import FastMCP
import os
from fastapi import FastAPI
import pymysql
import logging
import asyncio
import uvicorn
from mcp import ClientSession
from mcp.client.sse import sse_client
from connections import get_connection, get_product
logger = logging.getLogger("H2_SERVER")
mcp = FastMCP("Warehouse H2")
BUYER_URLS = {
    "R1": os.getenv("RESTAURANT1_URL", "http://127.0.0.1:8002/sse"),
    "R2": os.getenv("RESTAURANT2_URL", "http://127.0.0.1:8003/sse"),
}
# Warehouse as a seller agent MCP tools
# Step 1 Agent checks availability of the product in the warehouse
@mcp.tool
def check_availability(sender_id: str ,item: Item, receiver_id: str="H2",
    message_type: str="AVAILABILITY_REQUEST") -> Availability_Response:
    """
    Checks whether the requested quantity of a product is available.
    """
    product = get_product(item.name)

    if product is None:
        return Availability_Response(
            sender_id="H2",
            receiver_id=sender_id,
            message_type="AVAILABILITY_RESPONSE",
            item=item,
            is_available=False,
            available_quantity=0
        )

    quantity = product["quantity"]

    if quantity <= 0:
        return Availability_Response(
            sender_id="H2",
            receiver_id=sender_id,
            message_type="AVAILABILITY_RESPONSE",
            item=item,
            is_available=False,
            available_quantity=quantity
        )

    if item.quantity > quantity:
        return Availability_Response(
            sender_id="H2",
            receiver_id=sender_id,
            message_type="AVAILABILITY_RESPONSE",
            item=item,
            is_available=False,
            available_quantity=quantity
        )

    return Availability_Response(
        sender_id="H2",
        receiver_id=sender_id,
        message_type="AVAILABILITY_RESPONSE",
        item=item,
        is_available=True,
        available_quantity=quantity
    )

# Step 2 Warehouse responses to an restaurant's offer
@mcp.tool
def request_offer(sender_id: str,item: Item,receiver_id: str = "H2",
                  message_type: str = "CALL_FOR_PROPOSAL") -> Response_Offer:
    """
    Response to an offer for a specific product and quantity to restaurants.
    """
    request_Offer = Request_Offer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message_type=message_type,
        item=item
    )
    item = get_product(request_Offer.item.name)
    if item is None:
        return Response_Offer(
            sender_id="H2",
            receiver_id=request_Offer.sender_id,
            message_type="PROPOSAL",
            item=Item(
                name=request_Offer.item.name,
                quantity=request_Offer.item.quantity,
                price=request_Offer.item.price),
            total_cost=0.0)
    if request_Offer.item.quantity <= 0:
        return Response_Offer(
            sender_id="H2",
            receiver_id=request_Offer.sender_id,
            message_type="PROPOSAL",
            item=Item(
                name=request_Offer.item.name,
                quantity=request_Offer.item.quantity,
                price=request_Offer.item.price
            ),
            total_cost=0.0)

    return Response_Offer(
        sender_id="H2",
        receiver_id=request_Offer.sender_id,
        message_type="PROPOSAL",
        item=Item(
            name=request_Offer.item.name,
            quantity=request_Offer.item.quantity,
            price=item["price"]),
        total_cost=request_Offer.item.quantity * item["price"])

# Step 4 Agent finalizes the order 
async def send_delivery_to_buyer(buyer_id: str, delivery_payload: dict):
    '''
    Connect with restaurant and send demand to use receive_delivery
    '''
    buyer_url = BUYER_URLS.get(buyer_id)
    try:
        async with sse_client(buyer_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("receive_delivery", arguments=delivery_payload)
                logger.info(f"[H2 -> {buyer_id}] confirmation: {result}")
    except Exception as error:
        logger.error(f"[H2 -> {buyer_id} error with delivery: {error}")

@mcp.tool
async def accept_offer(sender_id: str, item: Item, total_cost: float,
    receiver_id: str = "H2", message_type: str = "ACCEPT_PROPOSAL") -> Accept_Offer:
    """
    Sales a product from the warehouse, updates stock and wallet, finalyy finalizing the order. 
    """
    accept_Offer = Accept_Offer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message_type=message_type,
        item=item,
        total_cost=total_cost
    )
    
    product = get_product(accept_Offer.item.name)
    if product is None or accept_Offer.item.quantity > product["quantity"]:
        return Reject(
            sender_id="H2",
            receiver_id=accept_Offer.receiver_id,
            message_type="REJECT_PROPOSAL",
            item=Item(
                name=accept_Offer.item.name,
                quantity=accept_Offer.item.quantity,
                price=accept_Offer.item.price
            )
        )

    connection = None
    cursor = None
    name = accept_Offer.item.name
    quantity = accept_Offer.item.quantity
    cost = quantity * product["price"]

    try:
        connection = get_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            """
            UPDATE warehouse2
            SET quantity = quantity - %s
            WHERE LOWER(name) = LOWER(%s) AND quantity >= %s
            """,
            (quantity, name, quantity)
        )
        connection.commit()
        logger.info(f"H2 sold {quantity} of {name}")
        cursor.execute(
            """
            INSERT INTO wallet_warehouse2 (sender_id, receiver_id, type, ballance)
            SELECT %s, 'H2', 'INCOME', COALESCE(MAX(ballance), 0) + %s
            FROM wallet_warehouse2
            """, 
            (accept_Offer.sender_id, cost)
        )
        connection.commit()
        logger.info(f"H2 earned {cost} PLN")

    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Problem with updating database {e}", exc_info=True)
        raise e
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    delivery = Delivery(
        sender_id="H2",
        receiver_id=sender_id,
        message_type="DELIVERY",
        item=Item(
            name=accept_Offer.item.name,
            quantity=accept_Offer.item.quantity,
            price=product["price"]),
        total_cost=cost)
    delivery_dict = delivery.model_dump() if hasattr(delivery, 'model_dump') else delivery.dict()
    await send_delivery_to_buyer(buyer_id=sender_id, delivery_payload={"delivery_data": delivery_dict})
    
    
    return Accept_Offer(
        sender_id="H2",
        receiver_id=accept_Offer.receiver_id,
        message_type="ACCEPT_PROPOSAL",
        item=Item(
            name=accept_Offer.item.name,
            quantity=accept_Offer.item.quantity,
            price=accept_Offer.item.price
        ),
        total_cost=cost
    )

# Warehouse as a buyer agent
# Step 5 Agent updates products after new purchase
@mcp.tool
def receive_delivery_from_producer(Delivery:Delivery):
    '''
    Updates the warehouse stock based on the received products from the producer.
    '''
    product = get_product(Delivery.item.name)
    bought_quantity=Delivery.item.quantity
    price=Delivery.item.price
    total_cost = bought_quantity * price
    try:
        connection=get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE warehouse2
            SET quantity = quantity + %s
            WHERE name = %s
            """,
            (bought_quantity, product["name"]))
        connection.commit()
        cursor.execute(
            """
            INSERT INTO wallet_warehouse2 (sender_id,receiver_id,type,ballance)
            SELECT "H2", %s, "EXPENSE", ballance - %s
            FROM wallet_warehouse2
            ORDER BY id DESC LIMIT 1
            """, (Delivery.sender_id,total_cost)
            )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def run_mcp_server():
    '''
    Running MCP server
    '''
    mcp.run(transport="sse", host="0.0.0.0", port=8005)

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    run_mcp_server()