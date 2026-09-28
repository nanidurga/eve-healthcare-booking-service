"""Request/response models for bookings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.enums import BookingStatus
from app.schemas.catalog import CentreResponse, DiagnosticTestResponse


class BookingCreate(BaseModel):
    centre_test_id: int = Field(
        gt=0,
        description="Id of the centre/test offering being booked "
        "(from GET /centres/{id}/tests).",
        examples=[1],
    )
    appointment_at: AwareDatetime = Field(
        description="Appointment time. Must include a timezone offset and be "
        "in the future.",
        examples=["2026-10-05T09:30:00+05:30"],
    )


class BookingCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=255, examples=["Feeling better"])


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: BookingStatus
    appointment_at: datetime
    amount: Decimal = Field(description="Price snapshotted when the booking was made.")
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime

    centre: CentreResponse
    test: DiagnosticTestResponse

    @classmethod
    def from_model(cls, booking) -> "BookingResponse":  # noqa: ANN001
        """Flatten booking -> centre_test -> {centre, test} for the client.

        The nesting is a storage concern; an API consumer wants the centre and
        the test side by side.
        """
        return cls(
            id=booking.id,
            status=booking.status,
            appointment_at=booking.appointment_at,
            amount=booking.amount,
            cancellation_reason=booking.cancellation_reason,
            created_at=booking.created_at,
            updated_at=booking.updated_at,
            centre=CentreResponse.model_validate(booking.centre_test.centre),
            test=DiagnosticTestResponse.model_validate(booking.centre_test.test),
        )
