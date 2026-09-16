from pydantic import BaseModel, Field
from typing import Optional

class Item(BaseModel): # Reprezentuje pojedynczy produkt w komunikacji.
    name: str = Field(..., description="Nazwa produktu, np. tomatoes")
    quantity: int = Field(..., description="Ilość produktu")
    price: Optional[float] = Field(default=None, description="Cena za sztukę/kg (tylko w ofertach i dostawach)")

class AvailabilityRequest(BaseModel): # Wiadomość wysyłana do hurtowni, by sprawdzić, czy ma dany towar.
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="AVAILABILITY_REQUEST")
    item: Item

    @model_validator(mode="after")
    """Walidator uruchamiany po utworzeniu obiektu.
    Gwarantuje, że zapytanie o dostępność NIGDY nie wyśle ceny (czyści pole price na None).
    """
    def strip_price(self) -> "AvailabilityRequest":
        if self.item.price is not None:
            self.item.price = None
        return self

class CallForProposal(BaseModel): # Wiadomość wysyłana do hurtowni z prośbą o wycenę towaru.
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="CALL_FOR_PROPOSAL")
    item: Item

    @model_validator(mode="after")
    def strip_price(self) -> "CallForProposal":
        if self.item.price is not None:
            self.item.price = None
        return self

class Proposal(BaseModel): # Oferta cenowa (wycena) otrzymana od hurtowni.
    sender_id: str = Field(...)
    receiver_id: str = Field(default="R2")
    message_type: str = Field(default="PROPOSAL")
    item: Item
    total_cost: float

class AcceptProposal(BaseModel): # Komunikat wysyłany do zwycięskiej hurtowni, potwierdzający zakup.
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="ACCEPT_PROPOSAL")
    item: Item
    total_cost: float

class RejectProposal(BaseModel): # Komunikat informujący o odrzuceniu oferty (np. gdy hurtowni braknie towaru).
    sender_id: str = Field(default="R2")
    receiver_id: str = Field(...)
    message_type: str = Field(default="REJECT_PROPOSAL")
    item: Item

    @model_validator(mode="after")
    def strip_price(self) -> "RejectProposal":
        if self.item.price is not None:
            self.item.price = None
        return self

class Delivery(BaseModel): # Dokument dostawy potwierdzający, że towar dotarł do restauracji.
    sender_id: str = Field(...)
    receiver_id: str = Field(default="R2")
    message_type: str = Field(default="DELIVERY")
    item: Item
    total_cost: float