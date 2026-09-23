
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
from scheam import (Item, Delivery, Accept_Offer, Reject, 
                    Request_Offer, Response_Offer,Availability_Request, 
                    Availability_Response)
from fastmcp import FastMCP
from connections import get_connection, get_product
import httpx
import logging



logger = logging.getLogger("R2_CLIENT")
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
SYSTEM_PROMPT="""
Jesteś drugą hurtownią z ID H2 w łańcuchu dostaw. Twoim zadaniem jest przyjmowanie zamówień od producenta-P1 i przekazywanie ich do dwóch restauracji-R1 oraz R2.
Na stanie masz 11 produktów. Masz je podane po angielsku i w nawiasie dodatkowo niektóre po polsku: flour(mąka), passata(passata pomidorowa), mozzarella, parmigiano reggiano(parmezan), burrata, buffala, prosciutto cotto, prosciutto crudo, arugula(rukola), lamb's lettuce (rozszponka), salami. Ponadto jedna jednostka/sztuka produktu jest równowarta jednemu kilogramowi(np. gdy R1 lub R2 spyta H2 o 10kg mąki to sprawdzasz czy quantity jest >=10. Tak samo kupując od P1 5kg mozarelli, quantity tego produktu wzrośnie o 5).
Pełnisz dwie role:
1. Dla P1 jesteś kupcem/kupującym
2. Dla R1 i R2 jesteś sprzedawcą/sprzedającym
Jako kupiec masz na celu kupować od producenta P1, gdy jako H2 masz niewystarczająco produktów w magazynie po jego sprawdzeniu. Gdy masz wystarczającą ilość, nie kupuj produktu. Gdy jest go za mało ustal potrzebną ilość i poproś o ofertę producenta P1. Przed samym zakupem musisz sprawdzić aktualny balans portlefa i czy masz odpowiednio środków. Jeśli masz za mało pieniędzy odrzuć ofertę. Gdy ilość środków jest wystarczająca zaakceptuj oferte uzywając "accept_offer_from_producer". Jak zakup zostanie zaakcpetowany czekaj na wywołanie "receive delivery" i jak dostaniesz dostawę zaktualizuj swój magazyn i portfel. 
Jako sprzedawca jako H2 sprzedajesz te produkty do R1 i R2. Podczas sprzedaży produktu stosuj następujący protokół:
1. "check_availability" do sprawdzenia czy jako H2 posiadasz odpowiednią ilość produktów.
2. "request_offer" gdy masz w magazynie odpowiednią ilość produktów przygotuj ofertę dla kupującego
3. "accept_offer" po akcpetacji oferty, sprawdź stan magazynu przed transakcją, a jak wszytsko się będzie zgadzać to doporowadź do dostawy produktu do kupującego, zmiejszając ilość danego produktu w magazynie i resjestrując INCOME(przychód) w portfelu. Jezeli stan magazynu nie będzie się zgadzać przy akcpetacji, nie sprzedawaj produktu,odrzuć transakcję i poinformuj kupującego o odrzuceniu oferty.
Za kazdym razem sprawdzaj bazę danych(to znaczy stan portfela i ilości produktów) przed podjęciem jakiejkolwiek decyzji. Przy sprzedazy produktów, należy pamiętać o maksymalnych ilościach dostępnych na stanie, nie jesteś w stanie sprzedać więcej niż jest dostępne. Ponadto sprzedawać możesz tylko produkty, które są dostępne w hurtowni, w liczbach naturalnych . Nie możesz sprzedawać produktów, których nie masz na stanie.
Zawsze korzystaj z dostępnych narzędzi, aby badać stan faktyczny hurtowni i podejmować decyzje.  Odpowiadaj rzeczowo i precyzyjnie w języku polskim. Używaj standardowych typów komunikatów protokołu jezeli istnieją: "AVAILABILITY_REQUEST", "AVAILABILITY_RESPONSE","CALL_FOR_PROPOSAL","PROPOSAL","ACCEPT_PROPOSAL","REJECT_PROPOSAL","DELIVERY".
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

PRODUCER_URL = {"P1":os.getenv("PRODUCER_URL", "http://127.0.0.1:8001//sse")}

@tool
def get_proposal(item:str, quantity:int,price:float) -> Request_Offer:
    """
    Prepare request to producer to buy a specific product.
    """
    item=Item(
        name=item,
        quantity=quantity,
        price=price)
    request_Offer=Request_Offer(
        sender_id="H2",
        reciver_id="P1",
        message_type="CALL_FOR_PROPOSAL",
        item=item
    )
    if item["name"] is None:
        return stock_info(item.name)
    
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(PRODUCER_URL, json=request_Offer.model_dump())
            data = response.json() 
            return Response_Offer(
                sender_id="P1",
                receiver_id="H2",
                message_type="PROPOSAL",
                item=Item(
                    name=data["item"]["name"],
                    quantity=data["item"]["quantity"],
                    price=data["item"]["price"]))
    except Exception as exc:
        return Reject(
            sender_id="P1",
            receiver_id="H2",
            message_type="REJECT_PROPOSAL",
            item=item)
    
@tool
def accept_offer_from_producer(item: Item ,total_cost: float,
receiver_id: str = "H2", sender_id:str="P1",
message_type: str = "PROPOSAL") -> Accept_Offer:
    """
    Accepts an offer from the producer. Checks if the warehouse is able to purchase it.
    """
    Proposal=Response_Offer(sender_id=sender_id,
        receiver_id=receiver_id,
        message_type=message_type,
        item=item,
        total_cost=total_cost)
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
                sender_id="H2",
                receiver="P1",
                message_type="REJECT_PROPOSAL",
                item=Item(
                    name=Proposal.item.name,
                    quantity=quantity,
                    price=price))   
    finally:
        cursor.close()
        connection.close()

    accept_Offer=Accept_Offer(
        sender_id="H2",
        receiver="P1",
        message_type="ACCEPT_PROPOSAL",
        item=Item(
            name=Proposal.item.name,
            quantity=quantity,
            price=price),
        total_cost=total_cost)

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(PRODUCER_URL, json=accept_Offer.model_dump())
            return response.json()
    except Exception as exc:
        return f"{exc}"

tools = [stock_info, products_status, get_proposal, accept_offer_from_producer]
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    max_retries=5)
agent = create_agent(
    model=llm,
    system_prompt=SYSTEM_PROMPT,
    tools=tools,
    checkpointer=InMemorySaver())
config: RunnableConfig={"configurable":{"thread_id":"1"}}

