"""Request/response models for the centre and test catalogue."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticTestCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, examples=["CBC"])
    name: str = Field(min_length=2, max_length=160, examples=["Complete Blood Count"])
    description: str | None = Field(default=None, max_length=2000)
    preparation: str | None = Field(
        default=None, max_length=2000, examples=["Fasting for 8 hours."]
    )


class DiagnosticTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    preparation: str | None


class CentreCreate(BaseModel):
    name: str = Field(
        min_length=2, max_length=160, examples=["EVE Diagnostics - Banjara Hills"]
    )
    city: str = Field(min_length=2, max_length=80, examples=["Hyderabad"])
    address: str = Field(
        min_length=5, max_length=400, examples=["Road No. 12, Banjara Hills"]
    )
    phone: str | None = Field(default=None, max_length=20, examples=["+914012345678"])


class CentreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    city: str
    address: str
    phone: str | None
    is_active: bool


class CentreTestCreate(BaseModel):
    """Attach a catalogue test to a centre at that centre's price."""

    test_id: int = Field(gt=0)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2, examples=["450.00"])


class CentreTestResponse(BaseModel):
    """A bookable offering: one test, at one centre, at one price.

    Its ``id`` is the value a booking request refers to.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    price: Decimal
    is_active: bool
    test: DiagnosticTestResponse


class CentreTestWithCentreResponse(CentreTestResponse):
    centre: CentreResponse


class CentreDetailResponse(CentreResponse):
    tests: list[CentreTestResponse] = Field(default_factory=list)
