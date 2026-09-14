import data.sql_functions as sql_ops

def register_mcp_tools(mcp_server, agent_id: str):
    """Rejestruje narzędzia MCP dla agenta w serwerze MCP."""

    @mcp_server.tool()
    def check_availability(item_name: str, quantity: int) -> dict:
        """Narzędzie MCP: Sprawdza dostępność towaru w bazie."""
        row = sql_ops.db_get_product(item_name)

        available_qty = row["quantity"] if row else 0
        return {
            "item": item_name,
            "requested_quantity": quantity,
            "available_quantity": available_qty,
            "is_available": available_qty >= quantity,
        }

    @mcp_server.tool()
    def get_price_proposal(sender_id: str, item_name: str, quantity: int) -> dict:
        """Narzędzie MCP: Odbiera CALL_FOR_PROPOSAL i zwraca wycenę (PROPOSAL)."""
        row = sql_ops.db_get_product(item_name)

        if not row:
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_REQUEST",
                "reason": f"Product '{item_name}' not found.",
            }

        unit_price, available_quantity = row["price"], row["quantity"]

        if available_quantity < quantity:
            return {
                "sender_id": agent_id,
                "receiver_id": sender_id,
                "message_type": "REJECT_REQUEST",
                "reason": f"Insufficient stock. Requested: {quantity}, available: {available_quantity}.",
            }

        total = round(quantity * unit_price, 2)
        return {
            "sender_id": agent_id,
            "receiver_id": sender_id,
            "message_type": "PROPOSAL",
            "item": {
                "name": item_name,
                "quantity": quantity,
                "price": unit_price,
            },
            "total_cost": total,
        }


    @mcp_server.tool()
    def finalize_order(sender_id: str, item_name: str, quantity: int, total_cost: float) -> dict:
        """Narzędzie MCP: Odbiera ACCEPT_PROPOSAL i zwraca DELIVERY."""
        sql_ops.db_update_stock(item_name, quantity, 'subtract')

        return {
            "sender_id": agent_id,
            "receiver_id": sender_id,
            "message_type": "DELIVERY",
            "item": {"name": item_name, "quantity": quantity, "price": (total_cost / quantity)},
            "total_cost": total_cost,
        }