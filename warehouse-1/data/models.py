from typing import Optional
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    quantity: int
    unit: str  # np. "kg", "g", "l", "pcs", "pack"
    price: float = 0.0


class TradeMessage(BaseModel):
    """Uniwersalny model komunikacyji zgodnie ze specyfikacją JSON Schemas."""
    sender_id: str
    receiver_id: str
    message_type: str  # AVAILABILITY_REQUEST, CALL_FOR_PROPOSAL, ACCEPT_PROPOSAL, DELIVERY, REJECT_PROPOSAL itp.
    item: Item
    total_cost: float = 0.0
    is_available: Optional[bool] = None
    available_quantity: Optional[int] = None