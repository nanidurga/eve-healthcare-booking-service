"""Request/response models for payments and provider webhooks."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PaymentStatus
from app.schemas.booking import BookingResponse


class PaymentCreate(BaseModel):
    booking_id: int = Field(gt=0, examples=[1])
    force_status: PaymentStatus | None = Field(
        default=None,
        description="Test hook: force the simulated gateway's verdict. "
        "Only SUCCESS or FAILED are meaningful.",
        examples=["SUCCESS"],
    )
    mode: Literal["sync", "async"] = Field(
        default="sync",
        description=(
            "`sync` settles the payment immediately and updates the booking. "
            "`async` leaves the payment PENDING for the provider to settle via "
            "POST /payments/webhook — use it to exercise the webhook path."
        ),
    )


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider_reference: str = Field(
        description="The gateway's id for this transaction. Webhooks address "
        "payments by this value."
    )
    failure_reason: str | None
    created_at: datetime
    booking: BookingResponse


class WebhookRequest(BaseModel):
    """A payment-status callback from the simulated provider."""

    event_id: str = Field(
        min_length=1,
        max_length=128,
        description="The provider's unique id for this delivery. Redeliveries "
        "reuse it, and that is what makes this endpoint idempotent.",
        examples=["evt_9f2c1b"],
    )
    provider_reference: str = Field(
        min_length=1,
        max_length=64,
        description="Identifies the payment being updated.",
        examples=["pay_3f8a2c1d4e5b6a7c"],
    )
    status: PaymentStatus = Field(examples=["SUCCESS"])
    amount: Decimal | None = Field(
        default=None,
        ge=0,
        description="If supplied, must match the payment amount exactly.",
        examples=["450.00"],
    )
    failure_reason: str | None = Field(default=None, max_length=255)


class WebhookResponse(BaseModel):
    """Always returned with HTTP 200 when the delivery was understood.

    A provider retries on any non-2xx, so a duplicate must not be an error.
    """

    event_id: str
    outcome: Literal[
        "applied",
        "duplicate",
        "ignored_terminal_payment",
        "booking_not_updatable",
    ] = Field(
        description=(
            "`applied` - payment and booking updated. "
            "`duplicate` - this event_id was already processed; nothing changed. "
            "`ignored_terminal_payment` - the payment had already settled. "
            "`booking_not_updatable` - payment recorded, but the booking was in "
            "a state that must not change (for example, cancelled)."
        )
    )
    payment_status: PaymentStatus | None = None
    booking_status: str | None = None
    detail: str | None = None
