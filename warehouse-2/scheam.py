'''
Schemes valid with docs/schemas/json-schemas for warehouse 2
'''
from typing import Literal
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    quantity: int
    price: float | None = None

class DeliveryMessage(BaseModel):
    sender_id: str 
    receiver_id: str 
    message_type: Literal["DELIVERY"] = "DELIVERY"
    item: Item
    total_cost: float

class AcceptProposalMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["ACCEPT_PROPOSAL"] = "ACCEPT_PROPOSAL"
    item: Item
    total_cost: float

class RejectProposalMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["REJECT_PROPOSAL"] = "REJECT_PROPOSAL"
    item: Item

class CallForProposalMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["CALL_FOR_PROPOSAL"]= "CALL_FOR_PROPOSAL"
    item: Item

class ProposalMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["PROPOSAL"]='PROPOSAL'
    item: Item
    total_cost: float

class AvailabilityRequestMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["AVAILABILITY_REQUEST"] = "AVAILABILITY_REQUEST"
    item: Item

class AvailabilityResponseMessage(BaseModel):
    sender_id: str
    receiver_id: str
    message_type: Literal["AVAILABILITY_RESPONSE"] = "AVAILABILITY_RESPONSE"
    item: Item
    is_available: bool
    available_quantity: int