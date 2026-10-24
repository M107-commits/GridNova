from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class HouseholdEnergyUpdate(BaseModel):
    generation_wh: int = Field(ge=0, le=100_000)
    consumption_wh: int = Field(ge=0, le=100_000)
    preferred_price_paise: int | None = Field(default=None, ge=0, le=100_000)

class OfferCreate(BaseModel):
    household_id: int
    quantity_wh: int = Field(gt=0, le=100_000)
    price_paise_per_kwh: int = Field(ge=0, le=100_000)
    expires_in_hours: int = Field(default=24, ge=1, le=168)

class PurchaseRequest(BaseModel):
    buyer_household_id: int
    quantity_wh: int = Field(gt=0, le=100_000)

class GenerationCreate(BaseModel):
    household_id: int
    quantity_wh: int = Field(gt=0, le=100_000)
    source: Literal["solar", "wind", "hydro", "other"] = "solar"
    certificate_reference: str | None = Field(default=None, max_length=100)

class ReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)

class SimulationRequest(BaseModel):
    solar_percent: int = Field(ge=0, le=100)
    demand_percent: int = Field(ge=0, le=100)
    household_ids: list[int] | None = None

class SettingsUpdate(BaseModel):
    preferred_price_paise: int = Field(ge=0, le=100_000)
    share_surplus: bool

class HouseholdResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    city: str
    locality: str
    source: str
    capacity_wh: int
    generation_wh: int
    consumption_wh: int
    preferred_price_paise: int
    share_surplus: bool
