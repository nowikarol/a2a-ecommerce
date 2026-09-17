import data.sql_functions as sql_ops

def register_mcp_tools(mcp_server, agent_id: str):
    """Rejestruje narzędzia MCP dla agenta w serwerze MCP."""

    # =====================================================================
    # NARZĘDZIA FINANSOWE
    # =====================================================================
    @mcp_server.tool()
    def get_balance() -> dict:
        """Narzędzie MCP: Zwraca aktualny stan konta portfela."""
        balance = sql_ops.db_get_balance()
        return {"account_id": 1, "balance": balance, "currency": "PLN"}

    @mcp_server.tool()
    def get_transaction_history() -> dict:
        """Narzędzie MCP: Zwraca historię transakcji finansowych."""
        history = sql_ops.db_get_transaction_history()
        return {"transactions": history}

    # =====================================================================
    # NARZĘDZIA SPRZEDAJĄCEGO
    # =====================================================================
    @mcp_server.tool()
    def check_availability(sender_id: str, item_name: str, quantity: int) -> dict:
        """Narzędzie MCP: Sprawdza dostępność towaru w bazie i zwraca AVAILABILITY_RESPONSE."""
        row = sql_ops.db_get_product(item_name)
        unit = row["unit"] if row else None
        available_qty = row["quantity"] if row else 0
        is_available = available_qty >= quantity

        return {
            "sender_id": agent_id,
            "receiver_id": sender_id,
            "message_type": "AVAILABILITY_RESPONSE",
            "item": {
                "name": item_name,
                "quantity": quantity,
                "unit": unit
            },
            "is_available": is_available,
            "available_quantity": available_qty,
        }

    @mcp_server.tool()
    def request_offer(sender_id: str, item_name: str, quantity: int) -> dict:
        """Narzędzie MCP: Odbiera CALL_FOR_PROPOSAL i zwraca wycenę (PROPOSAL) lub REJECT_PROPOSAL."""
        row = sql_ops.db_get_product(item_name)

        if not row or row["quantity"] < quantity:
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": item_name, "quantity": quantity, "unit": row["unit"] if row else "pcs"},
            }

        unit_price, available_quantity, unit = row["price"], row["quantity"], row["unit"]
        total = round(quantity * unit_price, 2)

        return {
            "sender_id": agent_id,
            "receiver_id": sender_id,
            "message_type": "PROPOSAL",
            "item": {
                "name": item_name,
                "quantity": quantity,
                "unit": unit,
                "price": unit_price,
            },
            "total_cost": total,
        }

    @mcp_server.tool()
    def accept_offer(sender_id: str, item_name: str, quantity: int, price: float) -> dict:
        """Narzędzie MCP: Odbiera ACCEPT_PROPOSAL, wyda towar z magazynu i dodaje przychód."""
        row = sql_ops.db_get_product(item_name)
        available_quantity = row["quantity"] if row else 0
        unit = row["unit"] if row else "pcs"

        if available_quantity < quantity:
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": item_name, "quantity": quantity, "unit": unit},
            }

        total_cost = round(quantity * price, 2)

        # 1. Zdejmij towar z magazynu
        if not sql_ops.db_update_stock(item_name, quantity, "subtract"):
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": item_name, "quantity": quantity, "unit": unit},
            }

        # 2. Zarejestruj transakcję finansową (SALE)
        tx_success = sql_ops.db_record_transaction(transaction_partner=sender_id, transaction_type="SALE", 
                                                   item_name=item_name, quantity=quantity, total_cost=total_cost)

        if not tx_success:
            # Revers magazynu w przypadku błędu
            sql_ops.db_update_stock(item_name, quantity, "add")
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_PROPOSAL",
                "item": {"name": item_name, "quantity": quantity, "unit": unit},
            }

        return {
            "sender_id": agent_id,
            "receiver_id": sender_id,
            "message_type": "ACCEPT_PROPOSAL",
            "item": {
                "name": item_name,
                "quantity": quantity,
                "unit": unit,
                "price": price,
            },
            "total_cost": total_cost,
        }

    # =====================================================================
    # NARZĘDZIA KUPUJĄCEGO
    # =====================================================================
    @mcp_server.tool()
    def receive_delivery(sender_id: str, item_name: str, quantity: int, price: float, total_cost: float, unit: str) -> dict:
        """Narzędzie MCP: Opłaca zamówienie z konta i dodaje przyjętą dostawę do magazynu."""
        # 1. Poberz opłatę z konta (PROCUREMENT_PAYMENT)
        tx_success = sql_ops.db_record_transaction(
            transaction_partner=sender_id,
            transaction_type="PROCUREMENT_PAYMENT",
            item_name=item_name,
            quantity=quantity,
            total_cost=total_cost
        )

        if not tx_success:
            return {
                "status": "DELIVERY_FAILED",
                "message": f"Insufficient funds to process delivery for {item_name}.",
                "total_cost": total_cost,
            }

        # 2. Zwiększ stan magazynowy
        sql_ops.db_update_stock(item_name, quantity, "add")

        return {
            "status": "DELIVERY_RECEIVED",
            "message": f"Successfully added {quantity} {unit} of {item_name} to warehouse inventory.",
            "total_cost": total_cost,
        }