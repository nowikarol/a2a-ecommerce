"""
Database module for Restaurant 1 (restaurant-1).
Provides SQLite schema initialization, data seeding for 11 Italian ingredients,
recipe definitions, and financial account / wallet tracking using SQL queries.
"""

import logging
from pathlib import Path
import sqlite3
from typing import Optional, Union

logger = logging.getLogger("restaurant-1.database")

# 11 Official Italian Ingredients requested
INITIAL_INGREDIENTS = [
    {"name": "flour", "quantity": 60, "safety_threshold": 20, "reorder_quantity": 50, "unit": "kg"},
    {"name": "passata", "quantity": 50, "safety_threshold": 20, "reorder_quantity": 50, "unit": "kg"},
    {"name": "mozzarella", "quantity": 40, "safety_threshold": 15, "reorder_quantity": 40, "unit": "kg"},
    {"name": "parmigiano reggiano", "quantity": 25, "safety_threshold": 10, "reorder_quantity": 25, "unit": "kg"},
    {"name": "burrata", "quantity": 20, "safety_threshold": 8, "reorder_quantity": 20, "unit": "kg"},
    {"name": "buffala", "quantity": 25, "safety_threshold": 10, "reorder_quantity": 25, "unit": "kg"},
    {"name": "prosciutto cotto", "quantity": 30, "safety_threshold": 12, "reorder_quantity": 30, "unit": "kg"},
    {"name": "prosciutto crudo", "quantity": 30, "safety_threshold": 12, "reorder_quantity": 30, "unit": "kg"},
    {"name": "arugula", "quantity": 15, "safety_threshold": 6, "reorder_quantity": 15, "unit": "kg"},
    {"name": "lamb's lettuce", "quantity": 15, "safety_threshold": 6, "reorder_quantity": 15, "unit": "kg"},
    {"name": "salami", "quantity": 25, "safety_threshold": 10, "reorder_quantity": 25, "unit": "kg"},
]

# Authentic Italian dishes based solely on the 11 ingredients
INITIAL_RECIPES = [
    {
        "id": "margherita_classica",
        "name": "Pizza Margherita Classica",
        "description": "Klasyczna pizza neapolitańska z passatą pomidorową i mozzarellą",
        "ingredients": {"flour": 2, "passata": 3, "mozzarella": 2},
    },
    {
        "id": "pizza_diavola",
        "name": "Pizza Diavola",
        "description": "Pikantna pizza z passatą, mozzarellą i plasterkami włoskiego salami",
        "ingredients": {"flour": 2, "passata": 3, "mozzarella": 2, "salami": 2},
    },
    {
        "id": "pizza_prosciutto_cotto",
        "name": "Pizza Prosciutto Cotto",
        "description": "Wyśmienita pizza z sosem z passaty, mozzarellą i włoską szynką cotto",
        "ingredients": {"flour": 2, "passata": 2, "mozzarella": 2, "prosciutto cotto": 2},
    },
    {
        "id": "pizza_bufala",
        "name": "Pizza Bufala DOC",
        "description": "Pizza premium ze świeżą mozzarellą di bufala i parmigiano reggiano",
        "ingredients": {"flour": 2, "passata": 3, "buffala": 2, "parmigiano reggiano": 1},
    },
    {
        "id": "pizza_parma_arugula",
        "name": "Pizza Parma e Rucola",
        "description": "Pizza z passatą, mozzarellą, prosciutto crudo, świeżą rukolą i parmigiano reggiano",
        "ingredients": {
            "flour": 2,
            "passata": 2,
            "mozzarella": 2,
            "prosciutto crudo": 2,
            "arugula": 1,
            "parmigiano reggiano": 1,
        },
    },
    {
        "id": "insalata_burrata",
        "name": "Insalata Burrata e Crudo",
        "description": "Wykwintna sałatka ze świeżą burratą, roszponką, rukolą i prosciutto crudo",
        "ingredients": {
            "burrata": 2,
            "lamb's lettuce": 1,
            "arugula": 1,
            "prosciutto crudo": 1,
        },
    },
    {
        "id": "tagliere_italiano",
        "name": "Deska Wędlin i Serów Tagliere",
        "description": "Tradycyjny włoski półmisek: prosciutto crudo, cotto, salami, burrata i parmigiano",
        "ingredients": {
            "prosciutto crudo": 2,
            "prosciutto cotto": 2,
            "salami": 2,
            "burrata": 1,
            "parmigiano reggiano": 1,
            "lamb's lettuce": 1,
        },
    },
]


def get_connection(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Opens a SQLite connection with foreign keys enabled and Row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(
    db_path: Union[str, Path],
    initial_balance: float = 5000.0,
    currency: str = "PLN",
    seed: bool = True,
) -> None:
    """
    Initializes SQL database schema: inventory, recipes, recipe_ingredients,
    financial_account, and transactions. Seeds default data if tables are empty.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            # 1. Inventory table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    name TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    safety_threshold INTEGER NOT NULL DEFAULT 15,
                    reorder_quantity INTEGER NOT NULL DEFAULT 30,
                    unit TEXT NOT NULL DEFAULT 'kg'
                );
                """
            )

            # 2. Recipes table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT
                );
                """
            )

            # 3. Recipe ingredients relational mapping table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipe_ingredients (
                    recipe_id TEXT NOT NULL,
                    ingredient_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    PRIMARY KEY (recipe_id, ingredient_name),
                    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
                    FOREIGN KEY (ingredient_name) REFERENCES inventory(name) ON UPDATE CASCADE
                );
                """
            )

            # 4. Financial Account / Wallet table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_account (
                    account_id TEXT PRIMARY KEY,
                    currency TEXT NOT NULL DEFAULT 'PLN',
                    balance REAL NOT NULL CHECK(balance >= 0),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # 5. Financial transactions audit log
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    description TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES financial_account(account_id)
                );
                """
            )

            if seed:
                # Seed inventory if empty
                count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
                if count == 0:
                    for item in INITIAL_INGREDIENTS:
                        conn.execute(
                            """
                            INSERT INTO inventory (name, quantity, safety_threshold, reorder_quantity, unit)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                item["name"],
                                item["quantity"],
                                item["safety_threshold"],
                                item["reorder_quantity"],
                                item["unit"],
                            ),
                        )
                    logger.info(f"Seeded {len(INITIAL_INGREDIENTS)} initial ingredients into SQL inventory.")

                # Seed recipes if empty
                count_rec = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
                if count_rec == 0:
                    for rec in INITIAL_RECIPES:
                        conn.execute(
                            "INSERT INTO recipes (id, name, description) VALUES (?, ?, ?)",
                            (rec["id"], rec["name"], rec["description"]),
                        )
                        for ing_name, qty in rec["ingredients"].items():
                            conn.execute(
                                """
                                INSERT INTO recipe_ingredients (recipe_id, ingredient_name, quantity)
                                VALUES (?, ?, ?)
                                """,
                                (rec["id"], ing_name, qty),
                            )
                    logger.info(f"Seeded {len(INITIAL_RECIPES)} initial recipes into SQL recipes.")

                # Seed financial account if empty
                acc = conn.execute(
                    "SELECT COUNT(*) FROM financial_account WHERE account_id = 'R1_WALLET'"
                ).fetchone()[0]
                if acc == 0:
                    conn.execute(
                        """
                        INSERT INTO financial_account (account_id, currency, balance)
                        VALUES ('R1_WALLET', ?, ?)
                        """,
                        (currency, initial_balance),
                    )
                    conn.execute(
                        """
                        INSERT INTO transactions (account_id, transaction_type, amount, currency, description)
                        VALUES ('R1_WALLET', 'INITIAL_DEPOSIT', ?, ?, 'Initial restaurant operating balance')
                        """,
                        (initial_balance, currency),
                    )
                    logger.info(f"Seeded financial account 'R1_WALLET' with {initial_balance:.2f} {currency}.")

    finally:
        conn.close()
