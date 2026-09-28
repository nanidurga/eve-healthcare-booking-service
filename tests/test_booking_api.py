"""Integration tests for the booking endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.models.booking import Booking
from app.models.centre_test import CentreTest
from app.models.enums import BookingStatus
from tests.conftest import API, future, past


async def test_booking_starts_pending_with_the_offering_price(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": catalogue["offering_id"], "appointment_at": future()},
        headers=auth,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["amount"] == "450.00"
    assert body["centre"]["name"] == "EVE Banjara Hills"
    assert body["test"]["code"] == "CBC"


async def test_booking_price_is_snapshotted(
    client: AsyncClient, auth: dict, catalogue: dict, db, booking: dict
) -> None:
    """Re-pricing the offering must not change what an existing patient owes."""
    offering = await db.get(CentreTest, catalogue["offering_id"])
    offering.price = Decimal("777.00")
    await db.commit()

    response = await client.get(f"{API}/bookings/{booking['id']}", headers=auth)
    assert response.json()["amount"] == "450.00"


async def test_booking_requires_authentication(
    client: AsyncClient, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": catalogue["offering_id"], "appointment_at": future()},
    )
    assert response.status_code == 401


async def test_booking_an_unknown_offering_is_404(
    client: AsyncClient, auth: dict
) -> None:
    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": 9999, "appointment_at": future()},
        headers=auth,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "offering_not_found"


async def test_booking_a_withdrawn_offering_is_409(
    client: AsyncClient, auth: dict, catalogue: dict, db
) -> None:
    offering = await db.get(CentreTest, catalogue["offering_id"])
    offering.is_active = False
    await db.commit()

    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": catalogue["offering_id"], "appointment_at": future()},
        headers=auth,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offering_inactive"


async def test_past_appointment_is_rejected(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": catalogue["offering_id"], "appointment_at": past()},
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "appointment_in_past"


async def test_appointment_too_far_ahead_is_rejected(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["offering_id"],
            "appointment_at": future(days=400),
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "appointment_too_far_ahead"


async def test_naive_datetime_is_rejected(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    """Without an offset, 09:00 is ambiguous across timezones."""
    response = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["offering_id"],
            "appointment_at": "2099-01-01T09:00:00",
        },
        headers=auth,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_offset_datetimes_are_normalised_to_utc(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    """09:30 IST and 04:00 UTC are the same instant and must store identically."""
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(days=5)
    ist = ist.replace(microsecond=0)
    response = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["offering_id"],
            "appointment_at": ist.isoformat(),
        },
        headers=auth,
    )
    assert response.status_code == 201
    stored = datetime.fromisoformat(response.json()["appointment_at"])
    assert stored == ist
    assert stored.utcoffset() == timedelta(0)


async def test_duplicate_live_slot_is_a_conflict(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    when = future()
    payload = {"centre_test_id": catalogue["offering_id"], "appointment_at": when}
    first = await client.post(f"{API}/bookings", json=payload, headers=auth)
    second = await client.post(f"{API}/bookings", json=payload, headers=auth)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_booking"


async def test_cancelling_frees_the_slot(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    """The uniqueness rule covers live bookings only."""
    when = future()
    payload = {"centre_test_id": catalogue["offering_id"], "appointment_at": when}
    first = await client.post(f"{API}/bookings", json=payload, headers=auth)
    await client.post(f"{API}/bookings/{first.json()['id']}/cancel", headers=auth)

    again = await client.post(f"{API}/bookings", json=payload, headers=auth)
    assert again.status_code == 201


async def test_two_users_may_book_the_same_slot(
    client: AsyncClient, asha: dict, rahul: dict, catalogue: dict
) -> None:
    payload = {"centre_test_id": catalogue["offering_id"], "appointment_at": future()}
    first = await client.post(f"{API}/bookings", json=payload, headers=asha["headers"])
    second = await client.post(f"{API}/bookings", json=payload, headers=rahul["headers"])
    assert first.status_code == 201
    assert second.status_code == 201


async def test_cancel_records_the_reason(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    response = await client.post(
        f"{API}/bookings/{booking['id']}/cancel",
        json={"reason": "Feeling better"},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancellation_reason"] == "Feeling better"


async def test_cancel_without_a_body_is_allowed(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    response = await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=auth)
    assert response.status_code == 200


async def test_cancelling_twice_is_a_conflict(
    client: AsyncClient, auth: dict, booking: dict
) -> None:
    await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=auth)
    response = await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_cancelled"


@pytest.mark.parametrize("path", ["", "/cancel"])
async def test_another_users_booking_is_404_not_403(
    client: AsyncClient, booking: dict, rahul: dict, path: str
) -> None:
    """403 would confirm the id exists, letting a caller enumerate bookings."""
    url = f"{API}/bookings/{booking['id']}{path}"
    response = (
        await client.post(url, headers=rahul["headers"])
        if path
        else await client.get(url, headers=rahul["headers"])
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "booking_not_found"


async def test_listing_only_returns_your_own_bookings(
    client: AsyncClient, booking: dict, asha: dict, rahul: dict
) -> None:
    mine = await client.get(f"{API}/bookings", headers=asha["headers"])
    theirs = await client.get(f"{API}/bookings", headers=rahul["headers"])
    assert mine.json()["meta"]["total"] == 1
    assert theirs.json()["meta"]["total"] == 0


async def test_listing_filters_by_status(
    client: AsyncClient, auth: dict, catalogue: dict, booking: dict
) -> None:
    second = await client.post(
        f"{API}/bookings",
        json={
            "centre_test_id": catalogue["offering_id"],
            "appointment_at": future(days=9),
        },
        headers=auth,
    )
    await client.post(f"{API}/bookings/{second.json()['id']}/cancel", headers=auth)

    cancelled = await client.get(
        f"{API}/bookings", params={"status": "CANCELLED"}, headers=auth
    )
    assert [b["id"] for b in cancelled.json()["items"]] == [second.json()["id"]]

    pending = await client.get(
        f"{API}/bookings", params={"status": "PENDING"}, headers=auth
    )
    assert [b["id"] for b in pending.json()["items"]] == [booking["id"]]


async def test_listing_rejects_an_unknown_status(
    client: AsyncClient, auth: dict
) -> None:
    response = await client.get(
        f"{API}/bookings", params={"status": "NOT_A_STATUS"}, headers=auth
    )
    assert response.status_code == 422


async def test_unknown_booking_id_is_404(client: AsyncClient, auth: dict) -> None:
    response = await client.get(f"{API}/bookings/9999", headers=auth)
    assert response.status_code == 404


async def test_non_numeric_booking_id_is_422(client: AsyncClient, auth: dict) -> None:
    response = await client.get(f"{API}/bookings/abc", headers=auth)
    assert response.status_code == 422


async def test_slot_uniqueness_is_enforced_by_the_database(
    db, catalogue: dict, asha: dict
) -> None:
    """The rule is a database constraint, not just an application check.

    Two concurrent requests could both pass an application-level check; only
    the partial unique index actually prevents the second row.
    """
    when = datetime.now(UTC) + timedelta(days=11)
    for _ in range(2):
        db.add(
            Booking(
                user_id=asha["user"]["id"],
                centre_test_id=catalogue["offering_id"],
                appointment_at=when,
                amount=Decimal("450.00"),
                status=BookingStatus.PENDING,
            )
        )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
