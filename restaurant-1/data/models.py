"""
Data models and schema validation for Restaurant 1 (restaurant-1).
Compliant with Contract Net Protocol (CNP) and schemas in docs/schemas/.
"""

from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageType(str, Enum):
    """Supported CNP message types."""
    AVAILABILITY_REQUEST = "AVAILABILITY_REQUEST"
    AVAILABILITY_RESPONSE = "AVAILABILITY_RESPONSE"
    CALL_FOR_PROPOSAL = "CALL_FOR_PROPOSAL"
    PROPOSAL = "PROPOSAL"
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    REJECT_PROPOSAL = "REJECT_PROPOSAL"
    DELIVERY = "DELIVERY"



class Item(BaseModel):
    """
    Item model conforming to docs/schemas/item.json.
    For requests and rejections, price is omitted (None).
    For proposals and acceptances, price is included.
    """
    name: str = Field(..., description="Nazwa artykułu / surowca")
    quantity: int = Field(..., gt=0, description="Ilość artykułu")
    price: Optional[float] = Field(default=None, description="Cena jednostkowa (wymagana w ofertach i akceptacjach)")

    model_config = ConfigDict(extra="ignore")


class BaseCNPMessage(BaseModel):
    """Base class for Contract Net Protocol messages."""
    sender_id: str = Field(..., description="Identyfikator nadawcy komunikatu")
    receiver_id: str = Field(..., description="Identyfikator odbiorcy komunikatu")
    message_type: str = Field(..., description="Typ wiadomości CNP")

    model_config = ConfigDict(extra="ignore")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the model to a dictionary, omitting None fields."""
        return self.model_dump(exclude_none=True)

    def to_json(self) -> str:
        """Serializes the model to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class AvailabilityRequestMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/json-schemas/availability-request.json.
    Issued by the restaurant to wholesalers to check stock availability before price quotation.
    """
    sender_id: str = Field(default="R1", description="Restaurant identifier")
    receiver_id: str = Field(..., description="Wholesaler identifier (e.g. H1, H2)")
    message_type: Literal["AVAILABILITY_REQUEST"] = "AVAILABILITY_REQUEST"
    item: Item = Field(..., description="Sprawdzany artykuł i wymagana ilość")

    @model_validator(mode="after")
    def strip_price(self) -> "AvailabilityRequestMessage":
        if self.item.price is not None:
            self.item.price = None
        return self


class AvailabilityResponseMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/json-schemas/availability-response.json.
    Submitted by a wholesaler confirming availability of the requested quantity.
    """
    sender_id: str = Field(..., description="Wholesaler identifier (e.g. H1, H2)")
    receiver_id: str = Field(default="R1", description="Restaurant identifier")
    message_type: Literal["AVAILABILITY_RESPONSE"] = "AVAILABILITY_RESPONSE"
    item: Item = Field(..., description="Artykuł i żądana ilość")
    is_available: bool = Field(..., description="Czy wymagana ilość jest dostępna na stanie")
    available_quantity: Optional[int] = Field(default=None, description="Aktualnie dostępna ilość w magazynie hurtowni")


class CallForProposalMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/request-offer.json (CALL_FOR_PROPOSAL).
    Issued by the restaurant to wholesalers to request price proposals.
    """
    sender_id: str = Field(default="R1", description="Restaurant 1 identifier")
    receiver_id: str = Field(..., description="Wholesaler identifier (e.g. H1, H2)")
    message_type: Literal["CALL_FOR_PROPOSAL"] = "CALL_FOR_PROPOSAL"
    item: Item = Field(..., description="Zapotrzebowanie na artykuł")

    @model_validator(mode="after")
    def strip_price(self) -> "CallForProposalMessage":
        # Ensure price is not sent in CFP
        if self.item.price is not None:
            self.item.price = None
        return self


class ProposalMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/response-offer.json (PROPOSAL).
    Submitted by a wholesaler in response to a CALL_FOR_PROPOSAL.
    """
    sender_id: str = Field(..., description="Wholesaler identifier (e.g. H1, H2)")
    receiver_id: str = Field(default="R1", description="Restaurant 1 identifier")
    message_type: Literal["PROPOSAL"] = "PROPOSAL"
    item: Item = Field(..., description="Oferowany artykuł z ceną jednostkową")
    total_cost: float = Field(..., ge=0, description="Całkowity koszt oferty")

    @model_validator(mode="after")
    def validate_pricing(self) -> "ProposalMessage":
        if self.item.price is None:
            raise ValueError("Proposal item must include price per unit")
        return self


class AcceptProposalMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/accept-offer.json (ACCEPT_PROPOSAL).
    Issued by the restaurant to the winning wholesaler.
    """
    sender_id: str = Field(default="R1", description="Restaurant 1 identifier")
    receiver_id: str = Field(..., description="Winning wholesaler identifier (e.g. H1)")
    message_type: Literal["ACCEPT_PROPOSAL"] = "ACCEPT_PROPOSAL"
    item: Item = Field(..., description="Zaakceptowany artykuł z ceną jednostkową")
    total_cost: float = Field(..., ge=0, description="Całkowity koszt zamówienia")


class RejectProposalMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/reject-offer.json / reject.json (REJECT_PROPOSAL).
    Issued by wholesaler when out of stock in Step 4, or for protocol rejection.
    """
    sender_id: str = Field(default="R1", description="Sender identifier (e.g. R1 or H1)")
    receiver_id: str = Field(..., description="Receiver identifier (e.g. H2 or R1)")
    message_type: Literal["REJECT_PROPOSAL"] = "REJECT_PROPOSAL"
    item: Item = Field(..., description="Odrzucony artykuł")
    reason: Optional[str] = Field(default=None, description="Powód odrzucenia (np. OUT_OF_STOCK)")

    @model_validator(mode="after")
    def strip_price(self) -> "RejectProposalMessage":
        if self.item.price is not None:
            self.item.price = None
        return self


class DeliveryMessage(BaseCNPMessage):
    """
    Message conforming to docs/schemas/json-schemas/delivery.json (DELIVERY).
    Issued by the winning wholesaler to the restaurant to confirm goods arrival.
    """
    sender_id: str = Field(..., description="Wholesaler identifier (e.g. H1, H2)")
    receiver_id: str = Field(default="R1", description="Restaurant identifier")
    message_type: Literal["DELIVERY"] = "DELIVERY"
    item: Item = Field(..., description="Dostarczony artykuł z ceną jednostkową")
    total_cost: float = Field(..., ge=0, description="Całkowity koszt dostawy")


class InventoryItem(BaseModel):
    """Model for an item stored in pantry inventory."""
    quantity: int = Field(..., ge=0, description="Aktualna ilość na stanie")
    safety_threshold: int = Field(default=15, ge=0, description="Poziom minimalny / bufor bezpieczeństwa")
    reorder_quantity: int = Field(default=30, gt=0, description="Ilość domyślnie zamawiana przy uzupełnieniu")
    unit: str = Field(default="kg", description="Jednostka miary (np. kg, l, szt.)")


class Recipe(BaseModel):
    """Model for a restaurant recipe."""
    name: str = Field(..., description="Nazwa dania")
    description: str = Field(default="", description="Opis dania")
    ingredients: Dict[str, int] = Field(..., description="Wymagane ilości składników na 1 porcję")


class FinancialAccount(BaseModel):
    """Model representing restaurant financial account / wallet."""
    account_id: str = Field(default="R1_WALLET", description="Identyfikator portfela")
    currency: str = Field(default="PLN", description="Waluta konta")
    balance: float = Field(..., ge=0, description="Dostępne saldo środków")


class TransactionRecord(BaseModel):
    """Model for a financial transaction log entry."""
    account_id: str
    transaction_type: str
    amount: float
    currency: str
    description: str
    timestamp: Optional[str] = None


class ProposalEvaluationResult(BaseModel):
    """Result of evaluating competing proposals."""
    winning_wholesaler: str
    winning_total_cost: float
    unit_price: float
    decision_reason: str
    accept_proposal: Dict[str, Any]
    reject_proposals: List[Dict[str, Any]] = Field(default_factory=list)
    all_evaluated_proposals: List[Dict[str, Any]]
    current_balance: Optional[float] = None
    currency: Optional[str] = "PLN"
    is_affordable: Optional[bool] = True
