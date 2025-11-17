from typing import List, Annotated
from decimal import Decimal
from pydantic import BaseModel, Field, condecimal

# Each card entry in a deck
class Card(BaseModel):
    name: str
    code: str = Field(description="Unique card identifier, e.g., 'A4-66'")
    qty: int = Field(..., ge=1, description="Quantity of this card in the deck")

# Each deck within the set
class Deck(BaseModel):
    name: str
    win_pct: Annotated[
        Decimal,
        Field(max_digits=5, decimal_places=2, description="Win percentage (2 decimals)")
    ]
    share: Annotated[
        Decimal,
        Field(max_digits=5, decimal_places=2, description="Meta share (2 decimals)")
    ]
    cards: List[Card]

# Root schema for the set of decks
class RecipeSet(BaseModel):
    set: str = Field(description="Name of the current expansion set")
    decks: List[Deck]
