from pydantic import BaseModel

class Item(BaseModel):
    name: str
    quantity: int
    price: float = 0.0


class TradeMessage(BaseModel):
    """Uniwersalny model wiadomości."""
    sender_id: str
    receiver_id: str
    message_type: str  # CALL_FOR_PROPOSAL, ACCEPT_PROPOSAL, ...
    item: Item
    total_cost: float = 0.0