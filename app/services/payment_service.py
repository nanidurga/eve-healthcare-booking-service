"""Simulated payment processing and idempotent webhook handling.

No real gateway is involved. ``simulate_gateway`` stands in for one, and is
deterministic on purpose: a random verdict would make tests flaky and a
reviewer's manual run unreproducible.

The webhook handler is the most delicate part of this service. Its contract:

* the same ``event_id`` may arrive any number of times and must change state
  at most once;
* deliveries may arrive out of order, so a settled payment is never re-settled;
* a delivery is never answered with a 4xx that a provider would retry forever
  when the situation is not actually retryable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import insert_or_ignore
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services import booking_service

# Booking states from which a payment may be started.
PAYABLE_STATUSES = frozenset({BookingStatus.PENDING, BookingStatus.FAILED})

# How a settled payment maps onto the booking.
_BOOKING_OUTCOME = {
    PaymentStatus.SUCCESS: BookingStatus.CONFIRMED,
    PaymentStatus.FAILED: BookingStatus.FAILED,
}


@dataclass(frozen=True)
class WebhookResult:
    outcome: str
    payment_status: PaymentStatus | None = None
    booking_status: BookingStatus | None = None
    detail: str | None = None


def new_provider_reference() -> str:
    return f"pay_{uuid.uuid4().hex}"


def simulate_gateway(
    amount: Decimal, force_status: PaymentStatus | None = None
) -> tuple[PaymentStatus, str | None]:
    """Stand-in for a payment gateway.

    Deterministic: an amount whose minor units equal ``PAYMENT_FAILURE_CENTS``
    (13 by default) is declined. Everything else succeeds. ``force_status``
    overrides the rule so a caller can exercise either branch directly.
    """
    if force_status is PaymentStatus.FAILED:
        return PaymentStatus.FAILED, "Payment declined by simulated gateway (forced)."
    if force_status is PaymentStatus.SUCCESS:
        return PaymentStatus.SUCCESS, None

    minor_units = int((amount * 100) % 100)
    if minor_units == settings.payment_failure_cents:
        return PaymentStatus.FAILED, "Insufficient funds (simulated)."
    return PaymentStatus.SUCCESS, None


# ---------------------------------------------------------------------------
# Initiating a payment
# ---------------------------------------------------------------------------
async def create_payment(
    session: AsyncSession,
    *,
    user: User,
    booking_id: int,
    force_status: PaymentStatus | None = None,
    mode: str = "sync",
) -> Payment:
    """Start a payment for one of the caller's bookings.

    The booking row is locked for the duration so two concurrent attempts
    cannot both charge it. In ``sync`` mode the gateway settles inside the same
    transaction; in ``async`` mode the payment is left PENDING and settled later
    by a webhook.
    """
    # Ownership check first: an id belonging to someone else must 404 before we
    # take any lock or reveal anything about it.
    await booking_service.get_booking(session, user=user, booking_id=booking_id)

    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update()
    )
    if booking is None:  # pragma: no cover - the ownership check just found it
        raise NotFoundError(f"Booking {booking_id} was not found.", code="booking_not_found")

    if booking.status not in PAYABLE_STATUSES:
        raise ConflictError(
            f"A booking in state {booking.status} cannot be paid for.",
            code="booking_not_payable",
            details={"current_status": booking.status},
        )

    # Retrying after a decline puts the booking back in PENDING, so the state
    # machine sees a legal PENDING -> CONFIRMED move when the retry settles.
    if booking.status is BookingStatus.FAILED:
        booking_service.apply_transition(booking, BookingStatus.PENDING)

    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=PaymentStatus.PENDING,
        provider_reference=new_provider_reference(),
    )
    session.add(payment)

    if mode == "sync":
        status, failure_reason = simulate_gateway(booking.amount, force_status)
        _settle(payment, booking, status, failure_reason)

    try:
        await session.commit()
    except IntegrityError as exc:
        # uq_payments_one_pending_per_booking: another attempt is already in
        # flight for this booking (only reachable in async mode).
        await session.rollback()
        raise ConflictError(
            "A payment for this booking is already awaiting settlement.",
            code="payment_in_flight",
        ) from exc

    await session.refresh(payment)
    return payment


def _settle(
    payment: Payment,
    booking: Booking,
    status: PaymentStatus,
    failure_reason: str | None,
) -> BookingStatus:
    """Write a gateway verdict onto the payment and its booking.

    Returns the booking status afterwards. The booking is only moved when the
    state machine permits it, so a cancelled booking is never resurrected by a
    late settlement.
    """
    payment.status = status
    payment.failure_reason = failure_reason

    target = _BOOKING_OUTCOME[status]
    if booking.status is not target and booking_service.can_transition(
        booking.status, target
    ):
        booking_service.apply_transition(booking, target)
    return booking.status


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------
async def handle_webhook(
    session: AsyncSession,
    *,
    event_id: str,
    provider_reference: str,
    status: PaymentStatus,
    amount: Decimal | None,
    failure_reason: str | None,
    raw_payload: dict[str, Any],
) -> WebhookResult:
    """Apply a provider callback exactly once.

    Everything below happens in a single transaction:

    1. claim ``event_id`` with INSERT ... ON CONFLICT DO NOTHING RETURNING id;
       losing that race means this delivery is a duplicate and must stop here;
    2. lock the payment row, and the booking row, with SELECT ... FOR UPDATE;
    3. ignore the delivery if the payment has already settled (out-of-order or
       conflicting redelivery);
    4. otherwise settle the payment and move the booking.

    Because the claim and the state change share one transaction, a crash
    halfway through rolls the claim back too, so the provider's retry is safe.
    """
    now = datetime.now(UTC)

    claimed_id = await session.scalar(
        insert_or_ignore(
            WebhookEvent,
            {
                "event_id": event_id,
                "payload": raw_payload,
                "received_at": now,
            },
            conflict_columns=["event_id"],
        )
    )
    if claimed_id is None:
        # Another delivery of this same event already holds the claim. Nothing
        # to do, and the provider must see a 2xx so it stops retrying.
        await session.commit()
        return WebhookResult(
            outcome="duplicate",
            detail="This event_id has already been processed.",
        )

    event = await session.get(WebhookEvent, claimed_id)

    payment = await session.scalar(
        select(Payment)
        .where(Payment.provider_reference == provider_reference)
        .with_for_update()
    )
    if payment is None:
        # Record the delivery for audit, then reject it. A 404 is correct here:
        # retrying will not make an unknown reference exist.
        await _finish_event(session, event, outcome="unknown_payment", now=now)
        raise NotFoundError(
            f"No payment found for provider_reference {provider_reference!r}.",
            code="payment_not_found",
        )

    event.payment_id = payment.id

    if amount is not None and amount != payment.amount:
        await _finish_event(session, event, outcome="amount_mismatch", now=now)
        raise ValidationError(
            "Webhook amount does not match the payment amount.",
            code="amount_mismatch",
            details={"expected": str(payment.amount), "received": str(amount)},
        )

    if payment.status.is_terminal:
        # Already settled: an out-of-order or contradictory redelivery. Accept
        # the delivery, change nothing.
        await _finish_event(session, event, outcome="ignored_terminal_payment", now=now)
        return WebhookResult(
            outcome="ignored_terminal_payment",
            payment_status=payment.status,
            booking_status=(await session.get(Booking, payment.booking_id)).status,
            detail=f"Payment had already settled as {payment.status}.",
        )

    booking = await session.scalar(
        select(Booking).where(Booking.id == payment.booking_id).with_for_update()
    )
    booking_was = booking.status
    booking_now = _settle(payment, booking, status, failure_reason)

    moved = booking_now is not booking_was
    outcome = "applied" if moved else "booking_not_updatable"
    await _finish_event(session, event, outcome=outcome, now=now)

    return WebhookResult(
        outcome=outcome,
        payment_status=payment.status,
        booking_status=booking_now,
        detail=None
        if moved
        else f"Payment recorded; booking left in {booking_now} as that state is final.",
    )


async def _finish_event(
    session: AsyncSession, event: WebhookEvent, *, outcome: str, now: datetime
) -> None:
    """Stamp the ledger row and commit the whole unit of work."""
    event.outcome = outcome
    event.processed_at = now
    await session.commit()
