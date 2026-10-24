from pydantic import BaseModel, Field, ConfigDict, field_validator
import re
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
    household_ids: list[int] | None = Field(default=None, max_length=5)

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


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    household_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    city: str = Field(min_length=2, max_length=50)
    locality: str = Field(min_length=2, max_length=80)

    @field_validator("name", "household_name", "city", "locality")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

class LoginRequest(BaseModel):
    email: str = Field(min_length=6, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value
