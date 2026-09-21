from scheam import (Item, Delivery, Accept_Offer, Reject, 
                    Request_Offer, Response_Offer,Availability_Request, 
                    Availability_Response)
from fastmcp import FastMCP
import pymysql
from connections import get_connection, get_product

mcp = FastMCP("Warehouse H2")

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
    Request_Offer = Request_Offer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message_type=message_type,
        item=item
    )
    item = get_product(Request_Offer.item.name)
    if item is None:
        return Response_Offer(
            sender_id="H2",
            receiver_id=Request_Offer.sender_id,
            message_type="PROPOSAL",
            item=Item(
                name=Request_Offer.item.name,
                quantity=Request_Offer.item.quantity,
                price=Request_Offer.item.price),
            total_cost=0.0)
    if Request_Offer.item.quantity <= 0:
        return Response_Offer(
            sender_id="H2",
            receiver_id=Request_Offer.sender_id,
            message_type="PROPOSAL",
            item=Item(
                name=Request_Offer.item.name,
                quantity=Request_Offer.item.quantity,
                price=Request_Offer.item.price
            ),
            total_cost=0.0)

    return Response_Offer(
        sender_id="H2",
        receiver_id=Request_Offer.sender_id,
        message_type="PROPOSAL",
        item=Item(
            name=Request_Offer.item.name,
            quantity=Request_Offer.item.quantity,
            price=item["price"]),
        total_cost=Request_Offer.item.quantity * item["price"])

# Step 4 Agent finalizes the order 
@mcp.tool
def accept_offer(sender_id: str, item: Item,total_cost: float,
    receiver_id: str = "H2",message_type: str = "ACCEPT_PROPOSAL") -> Accept_Offer 
    """
    Sales a product from the warehouse, finalizing the order. 
    """
    accept_Offer=Accept_Offer(
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
                price=accept_Offer.item.price))

    return Accept_Offer(
            sender_id="H2",
            receiver_id=accept_Offer.receiver_id,
            message_type="ACCEPT_PROPOSAL",
            item=Item(
                name=accept_Offer.item.name,
                quantity=accept_Offer.item.quantity,
                price=accept_Offer.item.price),
            total_cost=accept_Offer.item.quantity * accept_Offer.item.price)


# Step 5 Warehouse delivers products and agent udates the warehouse stock
@mcp.tool
def receive_delivery(Accept_Offer: Accept_Offer) -> Delivery:
    """
    Updates the warehouse stock based on sold products.
    """
    connection = None
    cursor = None
    name=Accept_Offer.item.name
    item=get_product(name)
    quantity=Accept_Offer.item.quantity
    total_cost=quantity*item["price"]
    try:
        connection=get_connection()
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            """
            UPDATE warehouse2
            SET quantity = quantity - %s
            WHERE name = %s AND quantity >= %s
            """,
            (quantity,name, quantity)
            )
        connection.commit()
        cursor.execute(
            """
            INSERT INTO wallet_warehouse2 (sender_id,receiver_id,type,ballance)
            SELECT %s, 'H2', 'INCOME', ballance + %s
            FROM wallet_warehouse2
            ORDER BY id DESC LIMIT 1
            """, (Accept_Offer.sender_id,total_cost)
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    return Delivery(
        sender_id="H2",
        receiver_id=Accept_Offer.receiver_id,
        message_type="DELIVERY",
        item=Item(
            name=Accept_Offer.item.name,
            quantity=Accept_Offer.item.quantity,
            price=Accept_Offer.item.price),
        total_cost=Accept_Offer.item.quantity * Accept_Offer.item.price)

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