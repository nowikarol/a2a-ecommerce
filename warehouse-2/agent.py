from client import check_producer_availability, request_producer_proposal, accept_producer_proposal
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
Jako kupiec masz na celu kupować od producenta P1, gdy jako H2 masz niewystarczająco produktów w magazynie po jego sprawdzeniu, tzn. 30 lub mniej produktów wtedy wywołaj "restock". W innym przypadku gdy stwierdzisz, ze produktu jeest go za mało ustal potrzebną ilość i poproś o ofertę producenta P1. Przed samym zakupem musisz sprawdzić aktualny balans portlefa i czy masz odpowiednio środków. Jeśli masz za mało pieniędzy odrzuć ofertę. Gdy ilość środków jest wystarczająca zaakceptuj oferte uzywając "accept_offer_from_producer". Jak zakup zostanie zaakcpetowany czekaj na wywołanie "receive delivery" i jak dostaniesz dostawę zaktualizuj swój magazyn i portfel. 
Jako sprzedawca jako H2 sprzedajesz te produkty do R1 i R2. Podczas sprzedaży produktu stosuj następujący protokół:
1. "check_availability" do sprawdzenia czy jako H2 posiadasz odpowiednią ilość produktów.
2. "request_offer" gdy masz w magazynie odpowiednią ilość produktów przygotuj ofertę dla kupującego
3. "accept_offer" po akcpetacji oferty, sprawdź stan magazynu przed transakcją, a jak wszytsko się będzie zgadzać to doporowadź do dostawy produktu do kupującego, zmiejszając ilość danego produktu w magazynie i resjestrując INCOME(przychód) w portfelu. Jezeli stan magazynu nie będzie się zgadzać przy akcpetacji, nie sprzedawaj produktu,odrzuć transakcję i poinformuj kupującego o odrzuceniu oferty.
Za kazdym razem sprawdzaj bazę danych(to znaczy stan portfela i ilości produktów) przed podjęciem jakiejkolwiek decyzji. Przy sprzedazy produktów, należy pamiętać o maksymalnych ilościach dostępnych na stanie, nie jesteś w stanie sprzedać więcej niż jest dostępne. Ponadto sprzedawać możesz tylko produkty, które są dostępne w hurtowni, w liczbach naturalnych . Nie możesz sprzedawać produktów, których nie masz na stanie.
Zawsze korzystaj z dostępnych narzędzi, aby badać stan faktyczny hurtowni i podejmować decyzje.  Odpowiadaj rzeczowo i precyzyjnie w języku polskim. Używaj standardowych typów komunikatów protokołu jezeli istnieją: "AVAILABILITY_REQUEST", "AVAILABILITY_RESPONSE","CALL_FOR_PROPOSAL","PROPOSAL","ACCEPT_PROPOSAL","REJECT_PROPOSAL","DELIVERY".
"""

@tool
def stock_info(item:str) -> Item:
    """
    Returns stock information about a specific product.
    """
    product= get_product(item)

    if product is None:
        return Item(name=item,quantity=0, price=0)
    return Item(name=product.name,quantity=product.quantity,price=product.price)

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
async def get_proposal(item:Item) -> Response_Offer:
    """
    Prepare request to producer to buy a specific product.
    """
    result = await request_producer_proposal(item_name=item.name,quantity=item.quantity)

    if result.get("message_type") != "PROPOSAL":
        return Reject(sender_id="P1",
            receiver_id="H2",
            message_type="REJECT_PROPOSAL",
            item=item,
            total_cost=0.0)

    data = result["item"]

    return Response_Offer(sender_id="P1",
        receiver_id="H2",
        message_type="PROPOSAL",
        item=Item(
            name=data["name"],
            quantity=data["quantity"],
            price=data["price"]
        ),
        total_cost=result["total_cost"]
    )

@tool
async def accept_offer_from_producer(Proposal:Response_Offer) -> Accept_Offer:
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
    finally:
        cursor.close()
        connection.close()

    if current_balance < total_cost:
        return Reject(sender_id="P1",
            receiver="H2",
            message_type="REJECT_PROPOSAL",
            item=Item(
                name=Proposal.item.name,
                quantity=quantity,
                price=price))  

    proposal= await accept_producer_proposal(
        item_name=Proposal.item.name,
        quantity=quantity,
        price=price,
        total_cost=total_cost)
    return proposal

@tool
async def restock() -> str:
    """
    Checks products in warehouse2. If quantity is <=30 it automatically buys 50kg of product
    """
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT name, quantity, price FROM warehouse2
            WHERE quantity <= 30
            """)
        rows = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()

    if not rows:
        return "There is no need to restock anything"

    products = []
    for row in rows:
        product_name = row["name"]
        availability = await check_producer_availability(item_name=product_name,quantity=50)
        if availability.get("message_type") != "AVAILABILITY_RESPONSE":
            products.append(f"{product_name}: could not check availability at P1.")
            continue

        if not availability.get("is_available"):
            products.append(
                f"{product_name}: P1 does not have enough stock ")
            continue
        proposal = await get_proposal(Item(name=product_name,quantity=50))

        if proposal.get( "message_type") != "PROPOSAL":
            products.append(f"{product_name}: P1 rejects the offer.")
            continue

        accepted_offer = await accept_offer_from_producer(proposal)

        if accepted_offer.get("message_type") == "ACCEPT_PROPOSAL":
            products.append(
                f"{product_name}: H2 bought 50 kg."
            )
        else:
            products.append(
                f"{product_name}: Offer got rejected.")
    return "\n".join(products)


tools = [stock_info, products_status, get_proposal, accept_offer_from_producer,restock]
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    max_retries=5)
agent = create_agent(
    model=llm,
    system_prompt=SYSTEM_PROMPT,
    tools=tools,
    checkpointer=InMemorySaver())
config: RunnableConfig={"configurable":{"thread_id":"1"}}

