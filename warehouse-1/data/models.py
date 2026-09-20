from typing import Optional
from pydantic import BaseModel


class Item(BaseModel):
    name: str
    quantity: int
    unit: str # Jednostka miary (np. "kg", "pcs"...)
    price: float = 0.0


class TradeMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: str
    item: Item
    total_cost: float = 0.0
    is_available: Optional[bool] = None
    available_quantity: Optional[int] = None
    reason: Optional[str] = None


class AgentQuery(BaseModel):
    prompt: str
    thread_id: str = "h1_default_session"