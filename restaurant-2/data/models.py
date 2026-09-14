from pydantic import BaseModel, Field
from typing import Optional

class Item(BaseModel):
    name: str = Field(..., description="Nazwa produktu, np. tomatoes")
    quantity: int = Field(..., description="Ilość produktu")
    price: Optional[float] = Field(default=None, description="Cena za sztukę/kg (tylko w ofertach i dostawach)")

class AvailabilityRequest(BaseModel):
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="AVAILABILITY_REQUEST")
    item: Item

class CallForProposal(BaseModel):
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="CALL_FOR_PROPOSAL")
    item: Item

class Proposal(BaseModel):
    sender_id: str = Field(...)
    receiver_id: str = Field(default="R2")
    message_type: str = Field(default="PROPOSAL")
    item: Item
    total_cost: float

class AcceptProposal(BaseModel):
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="ACCEPT_PROPOSAL")
    item: Item
    total_cost: float

class RejectProposal(BaseModel):
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="REJECT_PROPOSAL")
    item: Item