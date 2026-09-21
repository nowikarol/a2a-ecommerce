from typing import Optional
import re
from pydantic import BaseModel, field_validator

class Item(BaseModel):
    name: str
    quantity: float
    unit: str = "kg"
    price: float | None = 0.0

    @field_validator("quantity", mode="before")
    def parse_quantity(cls, v):
        """Automatycznie czyści ilość (np. '3 kg' -> 3.0) przed walidacją."""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            match = re.search(r"[\d.]+", v)
            return float(match.group()) if match else 0.0
        return 0.0


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