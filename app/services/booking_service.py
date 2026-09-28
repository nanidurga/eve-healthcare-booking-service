"""Booking lifecycle.

The state machine below is the single authority on how a booking may move. The
payment service asks this module to apply a transition rather than assigning
``booking.status`` directly, so an illegal move is impossible to express
anywhere in the codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.errors import InvalidStateTransition, NotFoundError, ValidationError
from app.models.booking import Booking
from app.models.centre_test import CentreTest
from app.models.enums import BookingStatus
from app.models.user import User
from app.services import catalog_service

# How a booking is allowed to move. Anything not listed here is a 409.
#
#   PENDING ---payment SUCCESS--> CONFIRMED ---cancel--> CANCELLED
#      |                                                     ^
#      +---payment FAILED--> FAILED ---retry--> PENDING      |
#      |                        |                            |
#      +------------------------+---------cancel-------------+
#
# CANCELLED is terminal: a cancelled appointment must never silently come back
# to life because a late webhook arrived.
ALLOWED_TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    BookingStatus.PENDING: frozenset(
        {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED}
    ),
    BookingStatus.FAILED: frozenset({BookingStatus.PENDING, BookingStatus.CANCELLED}),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    BookingStatus.CANCELLED: frozenset(),
}

# A booking may not be made for a time that has already passed, nor absurdly
# far ahead. The small grace window absorbs clock skew between client and API.
PAST_GRACE = timedelta(minutes=1)
MAX_LEAD_TIME = timedelta(days=180)


def can_transition(current: BookingStatus, target: BookingStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def apply_transition(
    booking: Booking, target: BookingStatus, *, reason: str | None = None
) -> Booking:
    """Move a booking to ``target`` or raise ``InvalidStateTransition``.

    Moving to the status it already holds is rejected too: every caller that
    might legitimately re-apply a status (the webhook) checks first, so a
    duplicate here means a real logic error.
    """
    if not can_transition(booking.status, target):
        raise InvalidStateTransition(
            f"A booking in state {booking.status} cannot move to {target}.",
            details={"current_status": booking.status, "requested_status": target},
        )
    booking.status = target
    if target is BookingStatus.CANCELLED:
        booking.cancellation_reason = reason
    return booking


def _validate_appointment(appointment_at: datetime) -> datetime:
    appointment_at = appointment_at.astimezone(UTC)
    now = datetime.now(UTC)
    if appointment_at < now - PAST_GRACE:
        raise ValidationError(
            "Appointment time is in the past.",
            code="appointment_in_past",
            details={"appointment_at": appointment_at.isoformat()},
        )
    if appointment_at > now + MAX_LEAD_TIME:
        raise ValidationError(
            f"Appointments cannot be made more than {MAX_LEAD_TIME.days} days ahead.",
            code="appointment_too_far_ahead",
        )
    return appointment_at


def _with_relations(stmt):  # noqa: ANN001, ANN201
    """Eager-load everything a BookingResponse needs, in one round trip."""
    return stmt.options(
        joinedload(Booking.centre_test).joinedload(CentreTest.centre),
        joinedload(Booking.centre_test).joinedload(CentreTest.test),
    )


async def create_booking(
    session: AsyncSession, *, user: User, centre_test_id: int, appointment_at: datetime
) -> Booking:
    appointment_at = _validate_appointment(appointment_at)
    offering = await catalog_service.get_bookable_offering(session, centre_test_id)

    booking = Booking(
        user_id=user.id,
        centre_test_id=offering.id,
        appointment_at=appointment_at,
        # Snapshot the price: a later re-price must not change what this
        # patient owes.
        amount=offering.price,
        status=BookingStatus.PENDING,
    )
    session.add(booking)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The partial unique index on (user, offering, slot) for live bookings.
        await session.rollback()
        raise InvalidStateTransition(
            "You already have a live booking for this test at this time.",
            code="duplicate_booking",
        ) from exc

    return await get_booking(session, user=user, booking_id=booking.id)


async def get_booking(session: AsyncSession, *, user: User, booking_id: int) -> Booking:
    """Fetch a booking owned by ``user``.

    A booking belonging to somebody else is reported as 404, not 403: a 403
    would confirm that the id exists, letting a caller enumerate other
    patients' bookings.
    """
    stmt = _with_relations(
        select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    )
    booking = (await session.execute(stmt)).unique().scalar_one_or_none()
    if booking is None:
        raise NotFoundError(
            f"Booking {booking_id} was not found.", code="booking_not_found"
        )
    return booking


async def list_bookings(
    session: AsyncSession,
    *,
    user: User,
    status: BookingStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Booking], int]:
    stmt = select(Booking).where(Booking.user_id == user.id)
    if status is not None:
        stmt = stmt.where(Booking.status == status)

    total = await catalog_service.count_rows(session, stmt)
    rows = await session.execute(
        _with_relations(stmt).order_by(Booking.created_at.desc(), Booking.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.unique().scalars()), total


async def cancel_booking(
    session: AsyncSession, *, user: User, booking_id: int, reason: str | None
) -> Booking:
    booking = await get_booking(session, user=user, booking_id=booking_id)
    if booking.status is BookingStatus.CANCELLED:
        raise InvalidStateTransition(
            "This booking is already cancelled.", code="already_cancelled"
        )
    apply_transition(booking, BookingStatus.CANCELLED, reason=reason)
    await session.commit()
    return await get_booking(session, user=user, booking_id=booking_id)
