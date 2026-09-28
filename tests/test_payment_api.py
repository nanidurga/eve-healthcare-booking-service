"""Integration tests for the simulated payment endpoint."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.payment import Payment
from tests.conftest import API, future


async def pay(client: AsyncClient, auth: dict, booking_id: int, **extra):
    return await client.post(
        f"{API}/payments", json={"booking_id": booking_id, **extra}, headers=auth
    )


async def test_successful_payment_confirms_the_booking(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    response = await pay(client, auth, booking["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["amount"] == "450.00"
    assert body["provider_reference"].startswith("pay_")
    assert body["booking"]["status"] == "CONFIRMED"


async def test_declined_payment_fails_the_booking(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    """The .13 offering trips the deterministic decline rule."""
    created = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["declining_offering_id"],
            "appointment_at": future(),
        },
        headers=auth,
    )
    response = await pay(client, auth, created.json()["id"])
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert response.json()["failure_reason"]
    assert response.json()["booking"]["status"] == "FAILED"


async def test_a_failed_booking_can_be_retried(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    created = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["declining_offering_id"],
            "appointment_at": future(),
        },
        headers=auth,
    )
    booking_id = created.json()["id"]
    await pay(client, auth, booking_id)

    retry = await pay(client, auth, booking_id, force_status="SUCCESS")
    assert retry.status_code == 201
    assert retry.json()["booking"]["status"] == "CONFIRMED"


async def test_retry_creates_a_second_payment_row(
    client: AsyncClient, auth: dict, catalogue: dict, db
) -> None:
    """Attempts are an audit trail; a retry must not overwrite the failure."""
    created = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["declining_offering_id"],
            "appointment_at": future(),
        },
        headers=auth,
    )
    booking_id = created.json()["id"]
    await pay(client, auth, booking_id)
    await pay(client, auth, booking_id, force_status="SUCCESS")

    count = await db.scalar(
        select(func.count()).select_from(Payment).where(Payment.booking_id == booking_id)
    )
    assert count == 2


async def test_paying_a_confirmed_booking_is_a_conflict(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    await pay(client, auth, booking["id"])
    response = await pay(client, auth, booking["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_payable"


async def test_paying_a_cancelled_booking_is_a_conflict(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=auth)
    response = await pay(client, auth, booking["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_payable"


async def test_double_charge_is_prevented(
    client: AsyncClient, auth: dict, booking: dict, db
) -> None:
    """Two pay requests must leave exactly one successful payment."""
    await pay(client, auth, booking["id"])
    await pay(client, auth, booking["id"])

    count = await db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.booking_id == booking["id"])
    )
    assert count == 1


async def test_paying_another_users_booking_is_404(
    client: AsyncClient, booking: dict, rahul: dict
) -> None:
    response = await pay(client, rahul["headers"], booking["id"])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


async def test_paying_an_unknown_booking_is_404(client: AsyncClient, auth: dict) -> None:
    response = await pay(client, auth, 9999)
    assert response.status_code == 404


async def test_payment_requires_authentication(
    client: AsyncClient, booking: dict
) -> None:
    response = await client.post(f"{API}/payments", json={"booking_id": booking["id"]})
    assert response.status_code == 401


async def test_async_mode_leaves_the_payment_pending(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    response = await pay(client, auth, booking["id"], mode="async")
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert response.json()["booking"]["status"] == "PENDING"


async def test_a_second_in_flight_payment_is_rejected(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    """Only one payment may await settlement for a booking at a time."""
    await pay(client, auth, booking["id"], mode="async")
    response = await pay(client, auth, booking["id"], mode="async")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_in_flight"


async def test_invalid_payment_payloads_are_422(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    for payload in (
        {},
        {"booking_id": 0},
        {"booking_id": booking["id"], "mode": "telepathy"},
        {"booking_id": booking["id"], "force_status": "MAYBE"},
    ):
        response = await client.post(f"{API}/payments", json=payload, headers=auth)
        assert response.status_code == 422, payload
