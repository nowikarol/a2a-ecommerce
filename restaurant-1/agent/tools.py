"""
Tools registry and Gemini function-calling definitions for Restaurant 1 (restaurant-1).
Backed by SQLite relational database with ACID transactions and pure SQL queries.
Conforms to docs/schemas/ and Google AI Studio / Gemini function calling format.
"""

import json
import logging
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Union

CURRENT_DIR = Path(__file__).resolve().parent
RESTAURANT_DIR = CURRENT_DIR.parent
if str(RESTAURANT_DIR) not in sys.path:
    sys.path.insert(0, str(RESTAURANT_DIR))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import config
from data.database import get_connection, init_db
from data.models import (
    AcceptProposalMessage,
    AvailabilityRequestMessage,
    AvailabilityResponseMessage,
    CallForProposalMessage,
    DeliveryMessage,
    Item,
    ProposalMessage,
)
from network.mcp_client import WholesalerMCPClient, default_mcp_client

logger = logging.getLogger("restaurant-1.tools")


class RestaurantAgent:
    """
    Core business logic and state management for Restaurant 1 backed by SQLite SQL queries.
    """

    def __init__(
        self,
        agent_id: str = config.AGENT_ID,
        db_path: Optional[Union[str, Path]] = None,
        initial_balance: float = config.INITIAL_BALANCE,
        currency: str = config.DEFAULT_CURRENCY,
        inventory_path: Optional[Path] = None,
        recipes_path: Optional[Path] = None,
    ):
        self.agent_id = agent_id
        if db_path is not None:
            self.db_path = Path(db_path)
        elif inventory_path is not None:
            self.db_path = Path(inventory_path).parent / "restaurant.db"
        else:
            self.db_path = config.DB_PATH

        self.currency = currency
        self.initial_balance = initial_balance

        # Ensure database and tables are created and seeded
        init_db(self.db_path, initial_balance=self.initial_balance, currency=self.currency)
        logger.info(f"[{self.agent_id}] Initialized SQLite database at {self.db_path.name}")

    def get_conn(self) -> sqlite3.Connection:
        """Returns a configured SQLite database connection."""
        return get_connection(self.db_path)

    # -------------------------------------------------------------------------
    # Financial Account Operations (SQL)
    # -------------------------------------------------------------------------

    def get_financial_status(self) -> Dict[str, Any]:
        """
        Retrieves current wallet balance, currency, and recent transaction history via SQL.
        """
        conn = self.get_conn()
        try:
            cur = conn.execute(
                "SELECT account_id, currency, balance, updated_at FROM financial_account WHERE account_id = 'R1_WALLET'"
            )
            row = cur.fetchone()
            if not row:
                return {"status": "ERROR", "message": "Financial account not found."}

            balance = float(row["balance"])
            currency = row["currency"]
            updated_at = row["updated_at"]

            tx_cur = conn.execute(
                """
                SELECT id, transaction_type, amount, currency, description, timestamp
                FROM transactions
                WHERE account_id = 'R1_WALLET'
                ORDER BY id DESC
                LIMIT 5
                """
            )
            recent_txs = [
                {
                    "id": tx["id"],
                    "type": tx["transaction_type"],
                    "amount": float(tx["amount"]),
                    "currency": tx["currency"],
                    "description": tx["description"],
                    "timestamp": tx["timestamp"],
                }
                for tx in tx_cur.fetchall()
            ]

            logger.info(f"[{self.agent_id}] Financial check: balance = {balance:.2f} {currency}")

            return {
                "status": "SUCCESS",
                "restaurant_id": self.agent_id,
                "account_id": "R1_WALLET",
                "balance": balance,
                "currency": currency,
                "last_updated": updated_at,
                "recent_transactions": recent_txs,
            }
        finally:
            conn.close()

    def deposit_funds(self, amount: float, description: str = "Operating funds deposit") -> Dict[str, Any]:
        """Deposits funds into the restaurant wallet using an atomic SQL transaction."""
        if amount <= 0:
            return {"status": "ERROR", "message": f"Deposit amount must be positive, got {amount}"}

        conn = self.get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE financial_account
                    SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = 'R1_WALLET'
                    """,
                    (amount,),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (account_id, transaction_type, amount, currency, description)
                    VALUES ('R1_WALLET', 'DEPOSIT', ?, ?, ?)
                    """,
                    (amount, self.currency, description),
                )
                new_balance = conn.execute(
                    "SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'"
                ).fetchone()[0]

            logger.info(f"[{self.agent_id}] Deposited {amount:.2f} {self.currency}. New balance: {new_balance:.2f}")
            return {
                "status": "SUCCESS",
                "deposited_amount": amount,
                "new_balance": float(new_balance),
                "currency": self.currency,
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Inventory & Kitchen Operations (SQL)
    # -------------------------------------------------------------------------

    def check_inventory(self) -> Dict[str, Any]:
        """
        Inspects pantry stock via SQL query and classifies each item status against safety threshold.
        """
        conn = self.get_conn()
        try:
            cur = conn.execute(
                """
                SELECT name, quantity, safety_threshold, reorder_quantity, unit
                FROM inventory
                ORDER BY name ASC
                """
            )
            rows = cur.fetchall()

            low_stock = []
            detailed_inventory = {}

            for row in rows:
                name = row["name"]
                qty = row["quantity"]
                threshold = row["safety_threshold"]
                reorder = row["reorder_quantity"]
                unit = row["unit"]

                if qty <= 0:
                    status = "CRITICAL_EMPTY"
                    low_stock.append(name)
                elif qty <= threshold:
                    status = "LOW_STOCK"
                    low_stock.append(name)
                else:
                    status = "OK"

                detailed_inventory[name] = {
                    "quantity": qty,
                    "safety_threshold": threshold,
                    "reorder_quantity": reorder,
                    "unit": unit,
                    "status": status,
                }

            # Get wallet balance
            bal_row = conn.execute("SELECT balance, currency FROM financial_account WHERE account_id = 'R1_WALLET'").fetchone()
            current_bal = float(bal_row["balance"]) if bal_row else 0.0

            logger.info(
                f"[{self.agent_id}] Inventory checked (SQL): {len(rows)} items, {len(low_stock)} low stock: {low_stock}, balance: {current_bal:.2f} {self.currency}"
            )

            return {
                "restaurant_id": self.agent_id,
                "inventory": detailed_inventory,
                "low_stock_items": low_stock,
                "total_items": len(rows),
                "wallet_balance": current_bal,
                "currency": self.currency,
            }
        finally:
            conn.close()

    def consume_ingredients(
        self,
        dish_name: str,
        quantity: int = 1,
        auto_reorder: Optional[bool] = None,
        wholesalers: Optional[List[str]] = None,
        mcp_client: Optional[WholesalerMCPClient] = None,
    ) -> Dict[str, Any]:
        """
        Deducts ingredients required for dish_name * quantity in an atomic SQL transaction.
        Returns shortage details if insufficient ingredients exist without modifying stock.
        When auto_reorder is True (default from config), automatically initiates CNP procurement
        and places orders for any ingredients falling on or below safety threshold or on shortage.
        """
        if quantity <= 0:
            return {"status": "ERROR", "message": f"Quantity must be positive, got {quantity}"}

        should_auto_reorder = auto_reorder if auto_reorder is not None else config.AUTO_REORDER_ON_THRESHOLD
        target_wholesalers = wholesalers or ["H1", "H2"]

        conn = self.get_conn()
        try:
            # 1. Look up recipe by ID or Name (case-insensitive)
            cur = conn.execute(
                """
                SELECT id, name, description FROM recipes
                WHERE LOWER(id) = LOWER(?) OR LOWER(name) = LOWER(?)
                LIMIT 1
                """,
                (dish_name, dish_name),
            )
            recipe_row = cur.fetchone()

            if not recipe_row:
                avail_cur = conn.execute("SELECT id, name FROM recipes ORDER BY id ASC")
                available = [f"{r['id']} ({r['name']})" for r in avail_cur.fetchall()]
                return {
                    "status": "ERROR",
                    "message": f"Dish '{dish_name}' not found in database. Available dishes: {available}",
                }

            recipe_id = recipe_row["id"]
            dish_title = recipe_row["name"]

            # 2. Fetch required ingredients from recipe_ingredients
            ing_cur = conn.execute(
                """
                SELECT ri.ingredient_name, ri.quantity, i.quantity AS current_stock, i.reorder_quantity
                FROM recipe_ingredients ri
                LEFT JOIN inventory i ON LOWER(ri.ingredient_name) = LOWER(i.name)
                WHERE ri.recipe_id = ?
                """,
                (recipe_id,),
            )
            ingredients = ing_cur.fetchall()

            shortages: List[Dict[str, Any]] = []
            total_needed: Dict[str, int] = {}

            for item in ingredients:
                ing_name = item["ingredient_name"]
                per_dish = item["quantity"]
                required_amount = per_dish * quantity
                total_needed[ing_name] = required_amount
                current_stock = item["current_stock"] if item["current_stock"] is not None else 0
                reorder_qty = item["reorder_quantity"] if item["reorder_quantity"] is not None else 30

                if current_stock < required_amount:
                    deficit = required_amount - current_stock
                    suggested = max(deficit, reorder_qty)
                    shortages.append(
                        {
                            "item_name": ing_name,
                            "current_stock": current_stock,
                            "needed": required_amount,
                            "missing": deficit,
                            "suggested_procurement_quantity": suggested,
                        }
                    )

            if shortages:
                missing_names = [s["item_name"] for s in shortages]
                logger.warning(
                    f"[INVENTORY:SHORTAGE] Insufficient ingredients for {quantity}x '{dish_title}'. Shortages: {missing_names}"
                )

                auto_reorders = []
                if should_auto_reorder:
                    for s in shortages:
                        item_name = s["item_name"]
                        needed_qty = s["suggested_procurement_quantity"]
                        logger.info(
                            f"[INVENTORY:AUTO_REORDER_SHORTAGE] Triggering procurement for shortage of '{item_name}' (needed: {needed_qty})..."
                        )
                        try:
                            reorder_res = self.request_quotes_and_evaluate(
                                item_name=item_name,
                                quantity=needed_qty,
                                wholesalers=target_wholesalers,
                                auto_order=True,
                                mcp_client=mcp_client,
                            )
                            auto_reorders.append(
                                {
                                    "item_name": item_name,
                                    "quantity": needed_qty,
                                    "reason": "SHORTAGE",
                                    "reorder_result": reorder_res,
                                }
                            )
                        except Exception as e:
                            logger.error(f"[INVENTORY:AUTO_REORDER_ERROR] Failed to auto-reorder shortage '{item_name}': {e}")
                            auto_reorders.append(
                                {
                                    "item_name": item_name,
                                    "quantity": needed_qty,
                                    "reason": "SHORTAGE",
                                    "reorder_result": {"status": "ERROR", "message": str(e)},
                                }
                            )

                shortage_res = {
                    "status": "SHORTAGE",
                    "dish_name": dish_title,
                    "quantity_requested": quantity,
                    "shortages": shortages,
                    "message": f"Cannot prepare {quantity}x '{dish_title}'. Insufficient ingredients: {missing_names}. Procurement required.",
                }
                if should_auto_reorder:
                    shortage_res["auto_reorders"] = auto_reorders
                return shortage_res

            # 3. Perform atomic deduction in SQL transaction
            warnings = []
            remaining_inventory = {}

            with conn:
                for ing_name, req_qty in total_needed.items():
                    conn.execute(
                        "UPDATE inventory SET quantity = quantity - ? WHERE LOWER(name) = LOWER(?)",
                        (req_qty, ing_name),
                    )

                # Check new levels and thresholds
                for ing_name in total_needed.keys():
                    row = conn.execute(
                        "SELECT quantity, safety_threshold, reorder_quantity FROM inventory WHERE LOWER(name) = LOWER(?)",
                        (ing_name,),
                    ).fetchone()
                    rem_qty = row["quantity"]
                    thresh = row["safety_threshold"]
                    reorder = row["reorder_quantity"]
                    remaining_inventory[ing_name] = rem_qty

                    if rem_qty <= thresh:
                        warnings.append(
                            {
                                "item_name": ing_name,
                                "remaining_quantity": rem_qty,
                                "safety_threshold": thresh,
                                "reorder_quantity": reorder,
                            }
                        )
                        logger.warning(
                            f"[INVENTORY:THRESHOLD_BREACH] Ingredient '{ing_name}' fell below safety threshold! Current: {rem_qty}, Threshold: {thresh}"
                        )

            logger.info(f"[INVENTORY:CONSUME] Consumed ingredients for {quantity}x '{dish_title}': {total_needed}")

            auto_reorders = []
            if should_auto_reorder and warnings:
                for w in warnings:
                    item_name = w["item_name"]
                    rem_qty = w["remaining_quantity"]
                    thresh = w["safety_threshold"]
                    reorder_qty = w["reorder_quantity"]
                    order_qty = reorder_qty
                    logger.info(
                        f"[INVENTORY:AUTO_REORDER] Stock of '{item_name}' ({rem_qty}) <= safety threshold ({thresh}). "
                        f"Auto-triggering procurement of {order_qty} units (reorder_quantity)..."
                    )
                    try:
                        reorder_res = self.request_quotes_and_evaluate(
                            item_name=item_name,
                            quantity=order_qty,
                            wholesalers=target_wholesalers,
                            auto_order=True,
                            mcp_client=mcp_client,
                        )
                        auto_reorders.append(
                            {
                                "item_name": item_name,
                                "quantity": order_qty,
                                "reason": "SAFETY_THRESHOLD_BREACH",
                                "reorder_result": reorder_res,
                            }
                        )
                    except Exception as e:
                        logger.error(f"[INVENTORY:AUTO_REORDER_ERROR] Failed to auto-reorder '{item_name}': {e}")
                        auto_reorders.append(
                            {
                                "item_name": item_name,
                                "quantity": order_qty,
                                "reason": "SAFETY_THRESHOLD_BREACH",
                                "reorder_result": {"status": "ERROR", "message": str(e)},
                            }
                        )

            success_res = {
                "status": "SUCCESS",
                "dish_name": dish_title,
                "quantity_prepared": quantity,
                "consumed_ingredients": total_needed,
                "low_stock_warnings": warnings,
                "remaining_inventory": remaining_inventory,
            }
            if should_auto_reorder:
                success_res["auto_reorders"] = auto_reorders
            return success_res
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Contract Net Protocol (CNP) Operations
    # -------------------------------------------------------------------------

    def create_procurement_request(
        self, item_name: str, quantity: int, receiver_id: str = "H1"
    ) -> Dict[str, Any]:
        """Creates a formatted CALL_FOR_PROPOSAL message conforming to docs/schemas/request-offer.json."""
        if quantity <= 0:
            raise ValueError(f"Procurement quantity must be greater than 0, got {quantity}")

        cfp_msg = CallForProposalMessage(
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            item=Item(name=item_name, quantity=quantity),
        )

        logger.info(
            f"[CNP:CALL_FOR_PROPOSAL] Issued CFP to wholesaler '{receiver_id}': item='{item_name}', quantity={quantity}"
        )

        return cfp_msg.to_dict()

    def evaluate_proposals(
        self, proposals_list: Union[List[Dict[str, Any]], str]
    ) -> Dict[str, Any]:
        """
        Deterministically selects winning offer with min(total_cost).
        Verifies wallet balance in SQL database and warns/flags if total_cost exceeds balance.
        Generates ACCEPT_PROPOSAL for the winning wholesaler (unselected offers silently expire without sending REJECT_PROPOSAL per A2A protocol).
        """
        if isinstance(proposals_list, str):
            proposals_data = json.loads(proposals_list)
        else:
            proposals_data = proposals_list

        if not proposals_data:
            logger.error("[CNP:EVALUATION] Received empty proposal list.")
            return {"status": "ERROR", "message": "Proposals list is empty."}

        parsed_proposals: List[ProposalMessage] = []
        for p in proposals_data:
            try:
                parsed_proposals.append(ProposalMessage(**p))
            except Exception as e:
                logger.error(f"[CNP:EVALUATION] Invalid proposal payload: {p}. Error: {e}")
                raise ValueError(f"Invalid proposal payload from {p.get('sender_id')}: {e}")

        logger.info(
            f"[CNP:EVALUATION] Received {len(parsed_proposals)} proposals for '{parsed_proposals[0].item.name}' (qty: {parsed_proposals[0].item.quantity}):"
        )
        for prop in parsed_proposals:
            logger.info(
                f"  -> Wholesaler '{prop.sender_id}': total_cost={prop.total_cost:.2f} {self.currency} (unit_price={prop.item.price:.2f} {self.currency})"
            )

        winning_proposal = min(
            parsed_proposals,
            key=lambda p: (p.total_cost, p.item.price if p.item.price is not None else 0.0),
        )
        winner_id = winning_proposal.sender_id
        winning_cost = winning_proposal.total_cost

        # Query current wallet balance from SQL
        conn = self.get_conn()
        try:
            bal_row = conn.execute("SELECT balance, currency FROM financial_account WHERE account_id = 'R1_WALLET'").fetchone()
            current_balance = float(bal_row["balance"]) if bal_row else 0.0
        finally:
            conn.close()

        is_affordable = current_balance >= winning_cost
        if not is_affordable:
            logger.warning(
                f"[CNP:BUDGET_WARNING] Winning proposal cost ({winning_cost:.2f} {self.currency}) exceeds wallet balance ({current_balance:.2f} {self.currency})!"
            )
            decision_reason = (
                f"Minimal total cost selected ({winning_cost:.2f} {self.currency} from {winner_id}), "
                f"WARNING: Cost exceeds current wallet balance ({current_balance:.2f} {self.currency})!"
            )
        else:
            logger.info(
                f"[CNP:DECISION] Deterministic Rule min(total_cost) selected Winner: '{winner_id}' with total_cost={winning_cost:.2f} {self.currency} (Affordable: balance={current_balance:.2f})"
            )
            decision_reason = f"Minimal total cost selected ({winning_cost:.2f} {self.currency} from {winner_id})"

        accept_msg = AcceptProposalMessage(
            sender_id=self.agent_id,
            receiver_id=winner_id,
            item=Item(
                name=winning_proposal.item.name,
                quantity=winning_proposal.item.quantity,
                price=winning_proposal.item.price,
            ),
            total_cost=winning_cost,
        )

        # Zgodnie ze standardem protokołu A2A pozostali sprzedawcy nie otrzymują żadnej informacji
        # (oferty milcząco wygasają), dlatego nie generujemy ani nie wysyłamy wiadomości REJECT_PROPOSAL.

        return {
            "status": "SUCCESS",
            "winning_wholesaler": winner_id,
            "decision_rule": "min(total_cost)",
            "winning_total_cost": winning_cost,
            "unit_price": winning_proposal.item.price,
            "current_wallet_balance": current_balance,
            "currency": self.currency,
            "is_affordable": is_affordable,
            "decision_reason": decision_reason,
            "accept_proposal": accept_msg.to_dict(),
            "reject_proposals": [],
            "all_evaluated_proposals": [p.to_dict() for p in parsed_proposals],
        }

    def check_wholesaler_availability(
        self,
        item_name: str,
        quantity: int,
        wholesalers: Optional[List[str]] = None,
        mcp_client: Optional[WholesalerMCPClient] = None,
    ) -> Dict[str, Any]:
        """
        Weryfikuje dostępność danej ilości surowca w hurtowniach przed wysłaniem zapytań o cenę.
        Zwraca szczegółowe statusy hurtowni oraz listę hurtowni posiadających wystarczający stan.
        """
        if quantity <= 0:
            return {
                "status": "ERROR",
                "message": f"Quantity must be positive, got {quantity}",
                "item_name": item_name,
                "quantity": quantity,
            }

        client = mcp_client or default_mcp_client
        target_wholesalers = wholesalers or list(config.WHOLESALER_ENDPOINTS.keys())

        logger.info(
            f"[CNP:AVAILABILITY_CHECK] Sprawdzanie dostępności dla '{item_name}' (ilość={quantity}) w hurtowniach: {target_wholesalers}..."
        )

        availability_map = client.check_all_availability(
            item_name=item_name, quantity=quantity, wholesaler_ids=target_wholesalers
        )

        available_wholesalers = [
            w_id for w_id, res in availability_map.items() if res.get("is_available", False)
        ]
        is_any_available = len(available_wholesalers) > 0

        status = "AVAILABLE" if is_any_available else "UNAVAILABLE"
        if is_any_available:
            msg = f"Surowiec '{item_name}' w ilości {quantity} jest dostępny w hurtowniach: {available_wholesalers}."
            logger.info(f"[CNP:AVAILABILITY_CHECK] {msg}")
        else:
            msg = f"Surowiec '{item_name}' w ilości {quantity} jest niedostępny w żadnej z hurtowni {target_wholesalers}."
            logger.warning(f"[CNP:AVAILABILITY_CHECK] {msg}")

        return {
            "status": status,
            "item_name": item_name,
            "quantity": quantity,
            "is_available": is_any_available,
            "available_wholesalers": available_wholesalers,
            "wholesalers_contacted": target_wholesalers,
            "availability": availability_map,
            "message": msg,
        }

    def request_quotes_and_evaluate(
        self,
        item_name: str,
        quantity: int,
        wholesalers: Optional[List[str]] = None,
        auto_order: bool = False,
        mcp_client: Optional[WholesalerMCPClient] = None,
    ) -> Dict[str, Any]:
        """
        Dwuetapowy proces zakupowy:
        1. Przed wysłaniem zapytań o ceny sprawdza dostępność wymaganej ilości surowca w hurtowniach.
           Jeśli produkt jest niedostępny w żadnej hurtowni, przerywa proces i NIE wysyła zapytań o ceny.
        2. Jeśli produkt jest dostępny, wysyła zapytania cenowe (CALL_FOR_PROPOSAL -> PROPOSAL)
           wyłącznie do hurtowni posiadających towar na stanie, wybiera deterministycznie najtańszą ofertę
           min(total_cost), sprawdza budżet w SQL i opcjonalnie przesyła decyzje zakupowe.
        """
        client = mcp_client or default_mcp_client
        target_wholesalers = wholesalers or list(config.WHOLESALER_ENDPOINTS.keys())

        # Krok 1: Weryfikacja dostępności surowca w danej ilości
        avail_res = self.check_wholesaler_availability(
            item_name=item_name,
            quantity=quantity,
            wholesalers=target_wholesalers,
            mcp_client=client,
        )

        available_wholesalers = avail_res.get("available_wholesalers", [])

        # Jeśli towar nie jest dostępny, przerywamy proces - brak zapytań cenowych
        if not available_wholesalers:
            logger.warning(
                f"[CNP:PURCHASE_PROCESS] Zatrzymano proces zakupowy: surowiec '{item_name}' w ilości {quantity} "
                f"jest niedostępny w hurtowniach {target_wholesalers}. Nie wysłano zapytań o ceny."
            )
            return {
                "status": "UNAVAILABLE",
                "message": (
                    f"Produkt '{item_name}' w ilości {quantity} jest niedostępny w odpytanych hurtowniach "
                    f"({target_wholesalers}). Zapytania o ceny nie zostały wysłane."
                ),
                "item_name": item_name,
                "quantity": quantity,
                "wholesalers_contacted": target_wholesalers,
                "available_wholesalers": [],
                "availability_check": avail_res.get("availability", {}),
                "quotes_requested": False,
            }

        # Krok 2: Towar jest dostępny ("dopiero reszta") -> zapytania cenowe wyłącznie do dostępnych hurtowni
        logger.info(
            f"[CNP:MCP_QUOTES] Towar '{item_name}' (qty={quantity}) jest dostępny w: {available_wholesalers}. "
            f"Wysyłanie zapytań cenowych..."
        )

        quotes = client.fetch_all_quotes(
            item_name=item_name, quantity=quantity, wholesaler_ids=available_wholesalers
        )

        if not quotes:
            return {
                "status": "ERROR",
                "message": f"Nie udało się uzyskać ofert cenowych od hurtowni {available_wholesalers} dla '{item_name}'.",
                "item_name": item_name,
                "quantity": quantity,
                "wholesalers_contacted": available_wholesalers,
                "availability_check": avail_res.get("availability", {}),
                "available_wholesalers": available_wholesalers,
                "quotes_requested": False,
            }

        # Ocena ofert deterministyczną regułą min(total_cost)
        eval_result = self.evaluate_proposals(quotes)
        if eval_result.get("status") != "SUCCESS":
            return eval_result

        # Jeśli auto_order zaznaczony, wysyłamy zamówienie do zwycięzcy z obsługą Kroku 4 (fallback)
        dispatched_decisions = []
        order_confirmed = False

        if auto_order:
            # Sortujemy oferty rosnąco według total_cost (oraz ceny jednostkowej)
            sorted_candidates = sorted(
                eval_result.get("all_evaluated_proposals", []),
                key=lambda p: (
                    p.get("total_cost", float("inf")),
                    p.get("item", {}).get("price", float("inf")) if p.get("item") else float("inf"),
                ),
            )

            conn = self.get_conn()
            try:
                bal_row = conn.execute("SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'").fetchone()
                current_balance = float(bal_row["balance"]) if bal_row else 0.0
            finally:
                conn.close()

            for cand_prop in sorted_candidates:
                cand_id = cand_prop.get("sender_id")
                cand_cost = float(cand_prop.get("total_cost", 0.0))
                cand_item = cand_prop.get("item", {})

                if cand_cost > current_balance:
                    logger.warning(
                        f"[CNP:ORDER] Oferta hurtowni '{cand_id}' (koszt={cand_cost:.2f}) przekracza budżet ({current_balance:.2f}). Pomijanie..."
                    )
                    continue

                accept_msg = AcceptProposalMessage(
                    sender_id=self.agent_id,
                    receiver_id=cand_id,
                    item=Item(
                        name=cand_item.get("name", item_name),
                        quantity=cand_item.get("quantity", quantity),
                        price=cand_item.get("price"),
                    ),
                    total_cost=cand_cost,
                ).to_dict()

                logger.info(f"[CNP:ACCEPT_OFFER] Składanie zamówienia w hurtowni '{cand_id}' (koszt: {cand_cost:.2f} {self.currency})...")
                ack = client.send_decision(cand_id, accept_msg)
                dispatched_decisions.append(ack)

                # Krok 4: Weryfikacja odpowiedzi sprzedawcy
                if ack.get("status") == "REJECTED" or ack.get("message_type") == "REJECT_PROPOSAL":
                    reason = ack.get("reason", "OUT_OF_STOCK")
                    logger.warning(
                        f"[CNP:ORDER_REJECTED] Hurtownia '{cand_id}' odrzuciła zamówienie (powód: {reason}). "
                        "Przechodzenie do kolejnej oferty (fallback)..."
                    )
                    continue
                else:
                    # Sukces - sprzedawca potwierdził akceptację
                    logger.info(
                        f"[CNP:ORDER_CONFIRMED] Hurtownia '{cand_id}' potwierdziła przyjęcie zamówienia. "
                        "Pozostali sprzedawcy nie otrzymują żadnych powiadomień."
                    )
                    eval_result["winning_wholesaler"] = cand_id
                    eval_result["winning_total_cost"] = cand_cost
                    eval_result["unit_price"] = cand_item.get("price", 0.0)
                    eval_result["accept_proposal"] = accept_msg
                    eval_result["order_status"] = "ACCEPTED"
                    order_confirmed = True
                    break

            if not order_confirmed and sorted_candidates:
                logger.warning(
                    f"[CNP:ORDER_FAILED] Wszystkie oferty zostały odrzucone przez hurtownie (brak towaru) lub przekroczyły budżet."
                )
                eval_result["order_status"] = "ALL_SELLERS_REJECTED"
                eval_result["message"] = f"Wszyscy dostępni sprzedawcy odrzucili zamówienie na '{item_name}' (brak towaru w Kroku 4)."

        eval_result["auto_order_dispatched"] = auto_order and order_confirmed
        eval_result["dispatched_decisions"] = dispatched_decisions
        eval_result["availability_check"] = avail_res.get("availability", {})
        eval_result["available_wholesalers"] = available_wholesalers
        eval_result["quotes_requested"] = True
        return eval_result

    def receive_delivery(
        self,
        delivery_data: Optional[Union[Dict[str, Any], str, DeliveryMessage]] = None,
        item_name: Optional[str] = None,
        quantity: Optional[int] = None,
        supplier_id: Optional[str] = None,
        unit_price: Optional[float] = None,
        total_cost: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Punkt wejścia dla Hurtowni (zewnętrzne narzędzie MCP):
        Odbiera sformatowany dokument DELIVERY zgodny z docs/schemas/json-schemas/delivery.json.
        Waliduje komunikat WZ za pomocą modelu DeliveryMessage, przyjmuje towar do bazy SQL
        oraz rozlicza płatność z portfela finansowego.
        """
        if delivery_data is not None:
            if isinstance(delivery_data, str):
                data_dict = json.loads(delivery_data)
            elif isinstance(delivery_data, DeliveryMessage):
                data_dict = delivery_data.to_dict()
            else:
                data_dict = delivery_data
        else:
            item_n = item_name or ""
            qty = quantity or 0
            supp = supplier_id or "H1"
            price = unit_price or 0.0
            cost = total_cost if total_cost is not None else (qty * price)
            data_dict = {
                "sender_id": supp,
                "receiver_id": self.agent_id,
                "message_type": "DELIVERY",
                "item": {"name": item_n, "quantity": qty, "price": price},
                "total_cost": cost,
            }

        try:
            msg = DeliveryMessage(**data_dict)
        except Exception as e:
            logger.error(f"[CNP:DELIVERY_ERROR] Niepoprawny format dokumentu DELIVERY: {e}")
            return {"status": "INVALID_DOCUMENT", "message": f"Niepoprawny format dokumentu DELIVERY: {e}"}

        item_name_val = msg.item.name
        quantity_val = msg.item.quantity
        supplier_id_val = msg.sender_id
        cost_val = msg.total_cost

        if quantity_val <= 0:
            return {"status": "ERROR", "message": f"Delivery quantity must be positive, got {quantity_val}"}

        conn = self.get_conn()
        try:
            with conn:
                if cost_val > 0:
                    bal_row = conn.execute(
                        "SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'"
                    ).fetchone()
                    current_bal = float(bal_row["balance"]) if bal_row else 0.0

                    if current_bal < cost_val:
                        logger.warning(
                            f"[CNP:DELIVERY_REJECTED] Insufficient funds: {cost_val:.2f} {self.currency} > balance {current_bal:.2f} {self.currency}"
                        )
                        return {
                            "status": "INSUFFICIENT_FUNDS",
                            "message": f"Odrzucono przyjęcie dostawy od {supplier_id_val}: koszt {cost_val:.2f} {self.currency} przekracza saldo {current_bal:.2f} {self.currency}.",
                            "current_balance": current_bal,
                            "required_amount": cost_val,
                        }

                    conn.execute(
                        """
                        UPDATE financial_account
                        SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP
                        WHERE account_id = 'R1_WALLET'
                        """,
                        (cost_val,),
                    )
                    conn.execute(
                        """
                        INSERT INTO transactions (account_id, transaction_type, amount, currency, description)
                        VALUES ('R1_WALLET', 'PROCUREMENT_PAYMENT', ?, ?, ?)
                        """,
                        (cost_val, self.currency, f"Dostawa {quantity_val}x '{item_name_val}' od hurtowni {supplier_id_val}"),
                    )

                cur = conn.execute(
                    "SELECT quantity, safety_threshold FROM inventory WHERE LOWER(name) = LOWER(?)",
                    (item_name_val,),
                )
                row = cur.fetchone()

                if row:
                    conn.execute(
                        "UPDATE inventory SET quantity = quantity + ? WHERE LOWER(name) = LOWER(?)",
                        (quantity_val, item_name_val),
                    )
                    new_level = row["quantity"] + quantity_val
                    threshold = row["safety_threshold"]
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory (name, quantity, safety_threshold, reorder_quantity, unit)
                        VALUES (?, ?, 15, 30, 'kg')
                        """,
                        (item_name_val.lower(), quantity_val),
                    )
                    new_level = quantity_val
                    threshold = 15

                fin_row = conn.execute(
                    "SELECT balance FROM financial_account WHERE account_id = 'R1_WALLET'"
                ).fetchone()
                final_balance = float(fin_row["balance"]) if fin_row else 0.0

            logger.info(
                f"[CNP:DELIVERY] Przyjęto dostawę {quantity_val}x '{item_name_val}' od hurtowni '{supplier_id_val}'. "
                f"Nowy stan: {new_level}, Rozliczono: {cost_val:.2f} {self.currency}, Saldo: {final_balance:.2f} {self.currency}"
            )

            return {
                "status": "DELIVERY_RECEIVED",
                "message": f"Dostawa przyjęta pomyślnie od hurtowni '{supplier_id_val}'.",
                "item_name": item_name_val,
                "quantity_received": quantity_val,
                "supplier_id": supplier_id_val,
                "new_stock_level": new_level,
                "safety_threshold": threshold,
                "payment_deducted": cost_val,
                "remaining_wallet_balance": final_balance,
                "currency": self.currency,
            }
        finally:
            conn.close()

    def check_and_trigger_procurement(
        self, wholesalers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Scans inventory via SQL for items below safety threshold and emits CALL_FOR_PROPOSAL messages."""
        if wholesalers is None:
            wholesalers = ["H1", "H2"]

        inv_check = self.check_inventory()
        low_stock_items = inv_check["low_stock_items"]

        if not low_stock_items:
            logger.info(f"[{self.agent_id}:AUTONOMY] Inventory healthy. No restocking needed.")
            return {
                "status": "HEALTHY",
                "message": "All stock levels are above safety thresholds.",
                "low_stock_items": [],
                "generated_rfps": [],
                "wallet_balance": inv_check.get("wallet_balance", 0.0),
            }

        logger.warning(
            f"[{self.agent_id}:AUTONOMY] Triggering procurement for low-stock items: {low_stock_items}"
        )

        all_rfps = []
        for item_name in low_stock_items:
            item_data = inv_check["inventory"][item_name]
            current_qty = item_data.get("quantity", 0)
            threshold = item_data.get("safety_threshold", 15)
            reorder_qty = item_data.get("reorder_quantity", 30)
            order_qty = reorder_qty

            rfps_for_item = []
            for wh in wholesalers:
                rfp = self.create_procurement_request(
                    item_name=item_name,
                    quantity=order_qty,
                    receiver_id=wh,
                )
                rfps_for_item.append(rfp)

            all_rfps.append(
                {
                    "item_name": item_name,
                    "current_stock": current_qty,
                    "safety_threshold": threshold,
                    "ordered_quantity": order_qty,
                    "rfps": rfps_for_item,
                }
            )

        return {
            "status": "PROCUREMENT_TRIGGERED",
            "low_stock_items": low_stock_items,
            "generated_rfps": all_rfps,
            "wallet_balance": inv_check.get("wallet_balance", 0.0),
            "currency": self.currency,
        }

    def get_node_info(self) -> Dict[str, Any]:
        """Returns public node identity and CNP protocol capabilities for the A2A network."""
        return {
            "status": "ONLINE",
            "agent_id": self.agent_id,
            "name": config.AGENT_NAME,
            "role": "RESTAURANT",
            "protocol": "Contract Net Protocol (CNP) / Model Context Protocol (MCP)",
            "capabilities": ["receive_delivery"],
        }


# Global default instance of RestaurantAgent
default_agent = RestaurantAgent()


# ============================================================================
# Gemini Function-Calling Tools Specification (Google AI Studio / Gemini format)
# ============================================================================

GEMINI_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": "Zwraca aktualny stan magazynowy z bazy SQL, progi bezpieczeństwa, status surowców (flour, passata, mozzarella, parmigiano reggiano, burrata, buffala, prosciutto cotto, prosciutto crudo, arugula, lamb's lettuce, salami) oraz saldo portfela.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_status",
            "description": "Zwraca stan portfela finansowego restauracji (dostępny balans w PLN, walutę oraz historię ostatnich transakcji zakupu).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consume_ingredients",
            "description": "Odejmuje składniki z bazy SQL na podstawie wybranej receptury (np. margherita_classica, pizza_diavola, pizza_bufala, pizza_parma_arugula, pizza_prosciutto_cotto, insalata_burrata, tagliere_italiano). Gdy stan surowców spadnie poniżej progu bezpieczeństwa (safety_threshold) lub wystąpi brak (SHORTAGE), narzędzie automatycznie domawia surowce u najtańszego dostawcy w hurtowniach (auto_order).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_name": {
                        "type": "string",
                        "description": "Nazwa dania (np. margherita_classica, pizza_diavola, pizza_bufala, pizza_parma_arugula, pizza_prosciutto_cotto, insalata_burrata, tagliere_italiano)",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Liczba porcji dania do przygotowania (domyślnie 1)",
                    },
                    "auto_reorder": {
                        "type": "boolean",
                        "description": "Czy automatycznie zamówić surowce w hurtowni, gdy stan spadnie na/poniżej progu bezpieczeństwa lub wystąpi brak (domyślnie true)",
                    },
                },
                "required": ["dish_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_procurement_request",
            "description": "Tworzy sformatowaną wiadomość CALL_FOR_PROPOSAL zgodnie z docs/schemas/request-offer.json skierowaną do konkretnej hurtowni.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Nazwa surowca (np. flour, passata, mozzarella, parmigiano reggiano, burrata, buffala, prosciutto cotto, prosciutto crudo, arugula, lamb's lettuce, salami)",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Ilość zamawianego surowca (liczba całkowita > 0)",
                    },
                    "receiver_id": {
                        "type": "string",
                        "description": "Identyfikator docelowej hurtowni (np. H1, H2). Domyślnie 'H1'.",
                    },
                },
                "required": ["item_name", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_proposals",
            "description": "Analizuje oferty PROPOSAL od hurtowni, wybiera zwycięzcę min(total_cost), sprawdza dostępny budżet w portfelu SQL i generuje ACCEPT_PROPOSAL dla zwycięzcy (pozostali sprzedawcy nie otrzymują odrzucenia - oferty milcząco wygasają).",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposals_list": {
                        "type": "array",
                        "description": "Lista otrzymanych ofert hurtowni w formacie PROPOSAL.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sender_id": {"type": "string", "description": "ID hurtowni oferenta (np. H1, H2)"},
                                "receiver_id": {"type": "string", "description": "ID restauracji (R1)"},
                                "message_type": {"type": "string", "enum": ["PROPOSAL"]},
                                "item": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "quantity": {"type": "integer"},
                                        "price": {"type": "number"},
                                    },
                                    "required": ["name", "quantity", "price"],
                                },
                                "total_cost": {"type": "number"},
                            },
                            "required": ["sender_id", "message_type", "item", "total_cost"],
                        },
                    }
                },
                "required": ["proposals_list"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "receive_delivery",
            "description": "Zwiększa stan magazynowy po dostawie towaru i potrąca opłatę z portfela restauracji w bazie SQL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Nazwa dostarczonego składnika",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Ilość dostarczonego składnika (> 0)",
                    },
                    "supplier_id": {
                        "type": "string",
                        "description": "Identyfikator dostawcy (np. H1, H2). Domyślnie 'H1'.",
                    },
                    "unit_price": {
                        "type": "number",
                        "description": "Cena jednostkowa zakupu surowca (opcjonalna, do potrącenia płatności z salda)",
                    },
                },
                "required": ["item_name", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_and_trigger_procurement",
            "description": "Autonomicznie sprawdza w SQL stan zapasów i automatycznie generuje zestaw zapytań CALL_FOR_PROPOSAL dla surowców poniżej progu bezpieczeństwa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "wholesalers": {
                        "type": "array",
                        "description": "Lista hurtowni, do których należy wysłać zapytania ofertowe (domyślnie ['H1', 'H2'])",
                        "items": {"type": "string"},
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_wholesaler_availability",
            "description": "Sprawdza dostępność danej ilości surowca w hurtowniach (H1, H2) przed wysłaniem zapytań o ceny.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Nazwa surowca (np. flour, passata, mozzarella, burrata itp.)",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Wymagana ilość surowca (liczba całkowita > 0)",
                    },
                    "wholesalers": {
                        "type": "array",
                        "description": "Lista hurtowni do odpytania (domyślnie ['H1', 'H2'])",
                        "items": {"type": "string"},
                    },
                },
                "required": ["item_name", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_quotes_and_evaluate",
            "description": "5-etapowy proces zakupowy A2A: najpierw sprawdza dostępność wymaganej ilości surowca w hurtowniach (Krok 1), wysyła zapytania cenowe wyłącznie do dostępnych hurtowni (Krok 2), porównuje oferty regułą min(total_cost) i weryfikuje budżet (Krok 3), po czym składa zamówienie z automatycznym fallbackiem przy braku towaru u zwycięzcy (Krok 4). Pozostali sprzedawcy nie otrzymują odrzucenia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Nazwa zamawianego surowca (np. flour, passata, mozzarella, burrata, salami itp.)",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Ilość zamawianego surowca (liczba całkowita > 0)",
                    },
                    "wholesalers": {
                        "type": "array",
                        "description": "Lista hurtowni do odpytania (domyślnie ['H1', 'H2'])",
                        "items": {"type": "string"},
                    },
                    "auto_order": {
                        "type": "boolean",
                        "description": "Czy po wybraniu najtańszej oferty natychmiast wysłać zamówienie (ACCEPT_PROPOSAL) do hurtowni przez MCP (domyślnie false)",
                    },
                },
                "required": ["item_name", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deposit_funds",
            "description": "Wpłaca środki pieniężne (PLN) na konto portfela restauracji R1_WALLET i rejestruje wpłatę w audycie transakcji.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Kwota do wpłaty w PLN (wartość dodatnia > 0)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Opcjonalny opis źródła lub celu wpłaty",
                    },
                },
                "required": ["amount"],
            },
        },
    },
]


def execute_tool(
    name: str,
    arguments: Union[Dict[str, Any], str],
    agent: Optional[RestaurantAgent] = None,
) -> str:
    """
    Executes tool by name with parsed arguments and maps the result to standard JSON.
    """
    target_agent = agent or default_agent

    if isinstance(arguments, str):
        try:
            parsed_args = json.loads(arguments) if arguments.strip() else {}
        except Exception as e:
            logger.error(f"Failed to parse tool arguments string: {arguments}. Error: {e}")
            return json.dumps({"status": "ERROR", "message": f"Malformed JSON arguments: {e}"})
    else:
        parsed_args = arguments or {}

    logger.info(f"[TOOL_EXEC] Calling '{name}' with args={parsed_args}")

    try:
        if name == "check_inventory":
            res = target_agent.check_inventory()
        elif name == "get_financial_status":
            res = target_agent.get_financial_status()
        elif name == "consume_ingredients":
            dish_name = parsed_args.get("dish_name", "")
            quantity = int(parsed_args.get("quantity", 1))
            auto_reorder_arg = parsed_args.get("auto_reorder")
            auto_reorder = bool(auto_reorder_arg) if auto_reorder_arg is not None else None
            wholesalers = parsed_args.get("wholesalers")
            res = target_agent.consume_ingredients(
                dish_name=dish_name,
                quantity=quantity,
                auto_reorder=auto_reorder,
                wholesalers=wholesalers,
            )
        elif name == "create_procurement_request":
            item_name = parsed_args.get("item_name", "")
            quantity = int(parsed_args.get("quantity", 1))
            receiver_id = parsed_args.get("receiver_id", "H1")
            res = target_agent.create_procurement_request(
                item_name=item_name, quantity=quantity, receiver_id=receiver_id
            )
        elif name == "evaluate_proposals":
            proposals_list = parsed_args.get("proposals_list", [])
            res = target_agent.evaluate_proposals(proposals_list=proposals_list)
        elif name == "check_wholesaler_availability":
            item_name = parsed_args.get("item_name", "")
            quantity = int(parsed_args.get("quantity", 1))
            wholesalers = parsed_args.get("wholesalers")
            res = target_agent.check_wholesaler_availability(
                item_name=item_name, quantity=quantity, wholesalers=wholesalers
            )
        elif name == "request_quotes_and_evaluate":
            item_name = parsed_args.get("item_name", "")
            quantity = int(parsed_args.get("quantity", 1))
            wholesalers = parsed_args.get("wholesalers", ["H1", "H2"])
            auto_order = bool(parsed_args.get("auto_order", False))
            res = target_agent.request_quotes_and_evaluate(
                item_name=item_name,
                quantity=quantity,
                wholesalers=wholesalers,
                auto_order=auto_order,
            )
        elif name == "receive_delivery":
            delivery_data = parsed_args.get("delivery_data")
            if delivery_data is not None:
                res = target_agent.receive_delivery(delivery_data=delivery_data)
            else:
                res = target_agent.receive_delivery(**parsed_args)
        elif name == "check_and_trigger_procurement":
            wholesalers = parsed_args.get("wholesalers", ["H1", "H2"])
            res = target_agent.check_and_trigger_procurement(wholesalers=wholesalers)
        elif name == "deposit_funds":
            amount = float(parsed_args.get("amount", 0.0))
            description = parsed_args.get("description", "Manual deposit")
            res = target_agent.deposit_funds(amount=amount, description=description)
        elif name == "get_node_info":
            res = target_agent.get_node_info()
        else:
            res = {"status": "ERROR", "message": f"Unknown tool: '{name}'"}
    except Exception as e:
        logger.error(f"[TOOL_EXEC_ERROR] Tool '{name}' failed: {e}")
        res = {"status": "ERROR", "message": str(e)}

    return json.dumps(res, indent=2, ensure_ascii=False)
