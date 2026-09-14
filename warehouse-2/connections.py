from dotenv import load_dotenv
from random import randint
import mysql.connector
import os

load_dotenv()


def get_connection():
    return mysql.connector.connect(host=os.getenv("MYSQL_HOST"),port=int(os.getenv("MYSQL_PORT", 3306)),database=os.getenv("MYSQL_DATABASE"),
        user=os.getenv("MYSQL_USER"),password=os.getenv("MYSQL_PASSWORD"))


def get_product(item: str):
    connection = get_connection()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT name, quantity, price
            FROM warehouse WHERE name =%s
            """,
            (item,),
        )

        return cursor.fetchone()

    finally:
        cursor.close()
        connection.close()

