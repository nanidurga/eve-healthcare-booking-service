"""The webhook contract: deliver the same event as often as you like.

This is the part of the assignment most likely to be wrong in a subtle way, so
it gets its own file. The invariant under test throughout:

    replaying an event_id must never create a second payment, move a booking
    twice, or corrupt booking state.
"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.booking import Booking
from app.models.payment import Payment
from app.models.webhook_event import WebhookEvent
from tests.conftest import API, future


async def start_async_payment(client: AsyncClient, auth: dict, booking_id: int) -> str:
    """Create a payment that is left PENDING for the provider to settle."""
    response = await client.post(
        f"{API}/payments",
        json={"booking_id": booking_id, "mode": "async"},
        headers=auth,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    return response.json()["provider_reference"]


def event(reference: str, *, event_id: str = "evt_1", status: str = "SUCCESS", **extra):
    return {
        "event_id": event_id,
        "provider_reference": reference,
        "status": status,
        **extra,
    }


@pytest.fixture
def webhook(client: AsyncClient):
    async def _post(payload: dict, **kwargs):
        return await client.post(f"{API}/payments/webhook", json=payload, **kwargs)

    return _post


# ---------------------------------------------------------------------------
# The core guarantee
# ---------------------------------------------------------------------------
async def test_first_delivery_settles_payment_and_booking(
    client: AsyncClient, auth: dict, booking: dict, webhook
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])

    response = await webhook(event(reference))
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "applied"
    assert body["payment_status"] == "SUCCESS"
    assert body["booking_status"] == "CONFIRMED"


@pytest.mark.parametrize("deliveries", [2, 3, 5])
async def test_redelivery_changes_nothing(
    client: AsyncClient, auth: dict, booking: dict, webhook, db, deliveries: int
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    payload = event(reference)

    outcomes = []
    for _ in range(deliveries):
        response = await webhook(payload)
        assert response.status_code == 200, "a duplicate must never be an error"
        outcomes.append(response.json()["outcome"])

    assert outcomes[0] == "applied"
    assert set(outcomes[1:]) == {"duplicate"}

    payments = await db.scalar(
        select(func.count()).select_from(Payment).where(Payment.booking_id == booking["id"])
    )
    events = await db.scalar(select(func.count()).select_from(WebhookEvent))
    stored = await db.get(Booking, booking["id"])
    await db.refresh(stored)

    assert payments == 1, "no duplicate payment row"
    assert events == 1, "the ledger records the event once"
    assert stored.status == "CONFIRMED"


async def test_duplicates_answer_200_so_the_provider_stops_retrying(
    client: AsyncClient, auth: dict, booking: dict, webhook
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    await webhook(event(reference))
    assert (await webhook(event(reference))).status_code == 200


async def test_concurrent_deliveries_of_the_same_event(
    client: AsyncClient, auth: dict, booking: dict, webhook, db
) -> None:
    """Exactly one of eight simultaneous deliveries may apply.

    The claim is an INSERT ... ON CONFLICT DO NOTHING, so the winner is decided
    by the unique index rather than by a read-then-write check that could
    interleave.
    """
    reference = await start_async_payment(client, auth, booking["id"])
    payload = event(reference)

    responses = await asyncio.gather(*(webhook(payload) for _ in range(8)))

    assert {r.status_code for r in responses} == {200}
    outcomes = Counter(r.json()["outcome"] for r in responses)
    assert outcomes["applied"] == 1
    assert outcomes["duplicate"] == 7

    payments = await db.scalar(
        select(func.count()).select_from(Payment).where(Payment.booking_id == booking["id"])
    )
    assert payments == 1


async def test_distinct_events_for_the_same_payment_settle_once(
    client: AsyncClient, auth: dict, booking: dict, webhook, db
) -> None:
    """Two genuinely different events, same payment: the second is ignored.

    This is the out-of-order case -- a FAILED notification arriving after the
    payment already settled as SUCCESS must not flip the booking.
    """
    reference = await start_async_payment(client, auth, booking["id"])
    first = await webhook(event(reference, event_id="evt_a", status="SUCCESS"))
    second = await webhook(event(reference, event_id="evt_b", status="FAILED"))

    assert first.json()["outcome"] == "applied"
    assert second.status_code == 200
    assert second.json()["outcome"] == "ignored_terminal_payment"
    assert second.json()["booking_status"] == "CONFIRMED"

    stored = await db.get(Booking, booking["id"])
    await db.refresh(stored)
    assert stored.status == "CONFIRMED"


# ---------------------------------------------------------------------------
# Failure and edge cases
# ---------------------------------------------------------------------------
async def test_failed_webhook_fails_the_booking(
    client: AsyncClient, auth: dict, booking: dict, webhook
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    response = await webhook(
        event(reference, status="FAILED", failure_reason="Card declined")
    )
    assert response.json()["outcome"] == "applied"
    assert response.json()["booking_status"] == "FAILED"


async def test_unknown_provider_reference_is_404(webhook) -> None:
    """Retrying cannot make an unknown reference exist, so this is not a 5xx."""
    response = await webhook(event("pay_does_not_exist"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "payment_not_found"


async def test_unknown_reference_is_still_recorded_for_audit(webhook, db) -> None:
    await webhook(event("pay_does_not_exist", event_id="evt_audit"))
    stored = await db.scalar(
        select(WebhookEvent).where(WebhookEvent.event_id == "evt_audit")
    )
    assert stored is not None
    assert stored.outcome == "unknown_payment"
    assert stored.payment_id is None


async def test_amount_mismatch_is_rejected(
    client: AsyncClient, auth: dict, booking: dict, webhook, db
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    response = await webhook(event(reference, amount="9.99"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "amount_mismatch"

    stored = await db.get(Booking, booking["id"])
    await db.refresh(stored)
    assert stored.status == "PENDING", "a mismatched delivery must change nothing"


async def test_matching_amount_is_accepted(
    client: AsyncClient, auth: dict, booking: dict, webhook
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    response = await webhook(event(reference, amount="450.00"))
    assert response.json()["outcome"] == "applied"


async def test_webhook_cannot_revive_a_cancelled_booking(
    client: AsyncClient, auth: dict, booking: dict, webhook, db
) -> None:
    """The scenario the assignment calls out: no corrupted booking state."""
    reference = await start_async_payment(client, auth, booking["id"])
    await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=auth)

    response = await webhook(event(reference))
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "booking_not_updatable"
    assert body["payment_status"] == "SUCCESS", "the money still moved"
    assert body["booking_status"] == "CANCELLED"

    stored = await db.get(Booking, booking["id"])
    await db.refresh(stored)
    assert stored.status == "CANCELLED"


async def test_event_ids_are_scoped_globally_not_per_payment(
    client: AsyncClient, auth: dict, catalogue: dict, booking: dict, webhook
) -> None:
    """A provider's event_id is unique across its whole stream."""
    first_reference = await start_async_payment(client, auth, booking["id"])
    second = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["offering_id"],
            "appointment_at": future(days=7),
        },
        headers=auth,
    )
    second_reference = await start_async_payment(client, auth, second.json()["id"])

    await webhook(event(first_reference, event_id="evt_shared"))
    reused = await webhook(event(second_reference, event_id="evt_shared"))

    assert reused.json()["outcome"] == "duplicate"
    still_pending = await client.get(
        f"{API}/bookings/{second.json()['id']}", headers=auth
    )
    assert still_pending.json()["status"] == "PENDING"


async def test_the_ledger_records_what_it_decided(
    client: AsyncClient, auth: dict, booking: dict, webhook, db
) -> None:
    reference = await start_async_payment(client, auth, booking["id"])
    await webhook(event(reference, event_id="evt_ledger"))

    stored = await db.scalar(
        select(WebhookEvent).where(WebhookEvent.event_id == "evt_ledger")
    )
    assert stored.outcome == "applied"
    assert stored.processed_at is not None
    assert stored.payment_id is not None
    assert stored.payload["provider_reference"] == reference


async def test_webhook_needs_no_authentication(
    client: AsyncClient, auth: dict, booking: dict, webhook
) -> None:
    """The caller is the payment provider, not a logged-in user."""
    reference = await start_async_payment(client, auth, booking["id"])
    response = await webhook(event(reference))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"event_id": "evt_x"},
        {"event_id": "evt_x", "provider_reference": "pay_1"},
        {"event_id": "", "provider_reference": "pay_1", "status": "SUCCESS"},
        {"event_id": "evt_x", "provider_reference": "pay_1", "status": "WHATEVER"},
        {
            "event_id": "evt_x",
            "provider_reference": "pay_1",
            "status": "SUCCESS",
            "amount": "-5.00",
        },
    ],
)
async def test_malformed_webhooks_are_422(webhook, payload) -> None:
    response = await webhook(payload)
    assert response.status_code == 422


async def test_webhook_secret_is_enforced_when_configured(
    client: AsyncClient, auth: dict, booking: dict, webhook, monkeypatch
) -> None:
    from app.core.config import settings

    reference = await start_async_payment(client, auth, booking["id"])
    monkeypatch.setattr(settings, "webhook_secret", "s3cret")

    rejected = await webhook(event(reference))
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "invalid_webhook_secret"

    accepted = await webhook(event(reference), headers={"X-Webhook-Secret": "s3cret"})
    assert accepted.status_code == 200
    assert accepted.json()["outcome"] == "applied"
