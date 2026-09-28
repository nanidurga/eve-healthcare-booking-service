"""Simulated payment endpoints and the provider webhook."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.errors import AuthenticationError
from app.schemas.booking import BookingResponse
from app.schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    WebhookRequest,
    WebhookResponse,
)
from app.services import booking_service, payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pay for a booking (simulated gateway)",
    responses={
        404: {"description": "Booking not found, or not yours"},
        409: {"description": "Booking is not payable, or a payment is in flight"},
    },
)
async def create_payment(
    payload: PaymentCreate, session: SessionDep, current_user: CurrentUser
) -> PaymentResponse:
    """Charge a booking through the simulated gateway.

    In the default `sync` mode the gateway settles immediately and the booking
    moves to **CONFIRMED** or **FAILED**. In `async` mode the payment is left
    **PENDING** and settles when the provider calls
    `POST /payments/webhook`.
    """
    payment = await payment_service.create_payment(
        session,
        user=current_user,
        booking_id=payload.booking_id,
        force_status=payload.force_status,
        mode=payload.mode,
    )
    booking = await booking_service.get_booking(
        session, user=current_user, booking_id=payment.booking_id
    )
    return PaymentResponse(
        id=payment.id,
        booking_id=payment.booking_id,
        amount=payment.amount,
        status=payment.status,
        provider_reference=payment.provider_reference,
        failure_reason=payment.failure_reason,
        created_at=payment.created_at,
        booking=BookingResponse.from_model(booking),
    )


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Payment status callback from the provider (idempotent)",
    responses={
        200: {"description": "Delivery accepted; see `outcome` for what changed"},
        401: {"description": "Webhook secret is configured and did not match"},
        404: {"description": "provider_reference does not match any payment"},
        422: {"description": "Amount does not match the payment"},
    },
)
async def payment_webhook(
    payload: WebhookRequest,
    session: SessionDep,
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> WebhookResponse:
    """Accept a payment-status update.

    **Idempotent by `event_id`.** Redelivering the same event returns 200 with
    `outcome: "duplicate"` and changes nothing — no duplicate payment, no
    duplicate booking, no corrupted state.

    Unauthenticated by design: the caller is the payment provider, not a user.
    Set `WEBHOOK_SECRET` to require a matching `X-Webhook-Secret` header.
    """
    if settings.webhook_secret and x_webhook_secret != settings.webhook_secret:
        raise AuthenticationError(
            "Invalid webhook signature.", code="invalid_webhook_secret"
        )

    result = await payment_service.handle_webhook(
        session,
        event_id=payload.event_id,
        provider_reference=payload.provider_reference,
        status=payload.status,
        amount=payload.amount,
        failure_reason=payload.failure_reason,
        raw_payload=payload.model_dump(mode="json"),
    )
    return WebhookResponse(
        event_id=payload.event_id,
        outcome=result.outcome,
        payment_status=result.payment_status,
        booking_status=result.booking_status,
        detail=result.detail,
    )
