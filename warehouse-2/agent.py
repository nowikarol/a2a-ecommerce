
from dotenv import load_dotenv
import os
from langchain_core.tools import tool
import json
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.runnables import RunnableConfig
import langchain_google_genai
from random import randint
from langchain_google_genai import ChatGoogleGenerativeAI
import pymysql.cursors
from connections import get_product,get_connection
from scheam import (Item, Delivery, Accept_Offer, Reject, 
                    Request_Offer, Response_Offer,Availability_Request, 
                    Availability_Response)
from fastmcp import FastMCP
from connections import get_connection, get_product


load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
SYSTEM_PROMPT="""
Jesteś drugą hurtownią z ID H2 w łańcuchu dostaw. Twoim zadaniem jest przyjmowanie zamówień od producenta i przekazywanie ich do dwóch restauracji R1 i R2.
Na stanie masz 11 produktów flour, passata, mozzarella, parmigiano reggiano, burrata, buffala, prosciutto cotto, prosciutto crudo, arugula, lamb's lettuce, salami. 
Przy sprzedazy produktów, należy pamiętać o maksymalnych ilościach dostępnych na stanie, nie jesteś w stanie sprzedać więcej niż jest dostępne. Ponadto sprzedawać możesz tylko produkty, które są dostępne w hurtowni, w liczbach naturalnych . Nie możesz sprzedawać produktów, których nie masz na stanie.
Zawsze korzystaj z dostępnych narzędzi, aby badać stan faktyczny hurtowni i podejmować decyzje. Odpowiadaj rzeczowo i precyzyjnie w języku polskim
"""

@tool
def stock_info(product:str) -> Item:
    """
    Returns stock information about a specific product.
    """
    product= get_product(product)

    if product is None:
        return Item(name=product["name"],
                    quantity=0, price=0)

    return Item(name=product["name"],
        quantity=product["quantity"],
        price=product["price"])

@tool
def products_status() -> list[Item]:
    """
    Returns the status of all products in the warehouse.
    """
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT name, quantity, price FROM warehouse2"
        )
        rows = cursor.fetchall()
        return [f"{item[0]}: {item[1]}" for item in rows]
    finally:
        cursor.close()
        connection.close()

@tool
def get_proposal(product:Item) -> Request_Offer:
    """
    Prepare request to buy specific product.
    """
    if product["name"] is None:
        return stock_info(product.name)
    return Request_Offer(
        sender_id="P1",
        reciver_id="H2",
        message_type="CALL_FOR_PROPOSAL",
        item=product)
    
@tool
def accept_offer_from_producer(Proposal:Response_Offer) -> Accept_Offer:
    """
    Accepts an offer from the producer. Checks if the warehouse is able to purchase it.
    """
    quantity=Proposal.item.quantity
    price=Proposal.item.price
    total_cost=quantity*price
    connection=get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT ballance FROM wallet_warehouse2 ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        current_balance = row["ballance"]
        
        if current_balance < total_cost:
            return Reject(
                sender_id="P1",
                receiver="H2",
                message_type="REJECT_PROPOSAL",
                item=Item(
                    name=Proposal.item.name,
                    quantity=quantity,
                    price=price))   
    finally:
        cursor.close()
        connection.close()

    return Accept_Offer(
        sender_id="P1",
        receiver="H2",
        message_type="ACCEPT_PROPOSAL",
        item=Item(
            name=Proposal.item.name,
            quantity=quantity,
            price=price),
        total_cost=total_cost)

tools = [stock_info, products_status, get_proposal, accept_offer_from_producer]
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    max_retries=5,             
)
agent = create_agent(
    model=llm,
    system_prompt=SYSTEM_PROMPT,
    tools=tools,
    checkpointer=InMemorySaver(),
)
config: RunnableConfig={"configurable":{"thread_id":"1"}}

