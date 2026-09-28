"""Unit tests for the booking state machine and the simulated gateway.

These need no database: the transition table and the gateway rule are pure
functions, and they are where the domain rules actually live.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import InvalidStateTransition
from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.services.booking_service import (
    ALLOWED_TRANSITIONS,
    apply_transition,
    can_transition,
)
from app.services.payment_service import simulate_gateway

LEGAL = [
    (BookingStatus.PENDING, BookingStatus.CONFIRMED),
    (BookingStatus.PENDING, BookingStatus.FAILED),
    (BookingStatus.PENDING, BookingStatus.CANCELLED),
    (BookingStatus.FAILED, BookingStatus.PENDING),
    (BookingStatus.FAILED, BookingStatus.CANCELLED),
    (BookingStatus.CONFIRMED, BookingStatus.CANCELLED),
]

ILLEGAL = [
    (BookingStatus.CONFIRMED, BookingStatus.PENDING),
    (BookingStatus.CONFIRMED, BookingStatus.FAILED),
    (BookingStatus.CANCELLED, BookingStatus.PENDING),
    (BookingStatus.CANCELLED, BookingStatus.CONFIRMED),
    (BookingStatus.CANCELLED, BookingStatus.FAILED),
    (BookingStatus.FAILED, BookingStatus.CONFIRMED),
]


@pytest.mark.parametrize(("current", "target"), LEGAL)
def test_legal_transitions_are_allowed(current, target) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize(("current", "target"), ILLEGAL)
def test_illegal_transitions_are_rejected(current, target) -> None:
    assert not can_transition(current, target)


def test_cancelled_is_terminal() -> None:
    """A cancelled appointment must never come back to life."""
    assert ALLOWED_TRANSITIONS[BookingStatus.CANCELLED] == frozenset()


def test_every_status_has_a_transition_entry() -> None:
    """A status missing from the table would raise KeyError at runtime."""
    assert set(ALLOWED_TRANSITIONS) == set(BookingStatus)


def test_apply_transition_moves_the_booking() -> None:
    booking = Booking(status=BookingStatus.PENDING)
    apply_transition(booking, BookingStatus.CONFIRMED)
    assert booking.status is BookingStatus.CONFIRMED


def test_apply_transition_records_a_cancellation_reason() -> None:
    booking = Booking(status=BookingStatus.PENDING)
    apply_transition(booking, BookingStatus.CANCELLED, reason="Feeling better")
    assert booking.cancellation_reason == "Feeling better"


def test_apply_transition_raises_on_an_illegal_move() -> None:
    booking = Booking(status=BookingStatus.CANCELLED)
    with pytest.raises(InvalidStateTransition) as excinfo:
        apply_transition(booking, BookingStatus.CONFIRMED)
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["current_status"] is BookingStatus.CANCELLED


def test_apply_transition_rejects_a_no_op() -> None:
    """Re-applying the current status signals a caller-side logic error."""
    booking = Booking(status=BookingStatus.CONFIRMED)
    with pytest.raises(InvalidStateTransition):
        apply_transition(booking, BookingStatus.CONFIRMED)


# ---------------------------------------------------------------------------
# Simulated gateway
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("amount", ["450.00", "1.00", "999.99", "0.00"])
def test_gateway_approves_ordinary_amounts(amount) -> None:
    status, reason = simulate_gateway(Decimal(amount))
    assert status is PaymentStatus.SUCCESS
    assert reason is None


@pytest.mark.parametrize("amount", ["999.13", "0.13", "12345.13"])
def test_gateway_declines_the_configured_minor_units(amount) -> None:
    status, reason = simulate_gateway(Decimal(amount))
    assert status is PaymentStatus.FAILED
    assert reason


def test_gateway_is_deterministic() -> None:
    """Repeated calls with the same amount must agree, or tests turn flaky."""
    results = {simulate_gateway(Decimal("450.00"))[0] for _ in range(20)}
    assert results == {PaymentStatus.SUCCESS}


@pytest.mark.parametrize(
    ("forced", "amount"),
    [(PaymentStatus.FAILED, "450.00"), (PaymentStatus.SUCCESS, "999.13")],
)
def test_force_status_overrides_the_rule(forced, amount) -> None:
    status, _ = simulate_gateway(Decimal(amount), forced)
    assert status is forced
