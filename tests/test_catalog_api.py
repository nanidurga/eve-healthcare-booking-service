"""Integration tests for the centre and test catalogue."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import API


async def test_listing_centres_is_public(client: AsyncClient, catalogue: dict) -> None:
    """Patients browse before they have an account."""
    response = await client.get(f"{API}/centres")
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 2


async def test_centre_listing_filters_by_city(client: AsyncClient, catalogue: dict) -> None:
    response = await client.get(f"{API}/centres", params={"city": "hyderabad"})
    assert [c["name"] for c in response.json()["items"]] == ["EVE Banjara Hills"]


async def test_centre_listing_filters_by_test_code(
    client: AsyncClient, catalogue: dict
) -> None:
    response = await client.get(f"{API}/centres", params={"test_code": "lft"})
    assert [c["name"] for c in response.json()["items"]] == ["EVE Banjara Hills"]


async def test_centre_listing_paginates(client: AsyncClient, catalogue: dict) -> None:
    response = await client.get(f"{API}/centres", params={"limit": 1, "offset": 0})
    body = response.json()
    assert len(body["items"]) == 1
    assert body["meta"] == {"total": 2, "limit": 1, "offset": 0, "has_more": True}

    response = await client.get(f"{API}/centres", params={"limit": 1, "offset": 1})
    assert response.json()["meta"]["has_more"] is False


async def test_pagination_limit_is_bounded(client: AsyncClient, catalogue: dict) -> None:
    """A client must not be able to ask for the whole table."""
    response = await client.get(f"{API}/centres", params={"limit": 5000})
    assert response.status_code == 422


async def test_centre_detail_includes_offerings_with_prices(
    client: AsyncClient, catalogue: dict
) -> None:
    response = await client.get(f"{API}/centres/{catalogue['centre_id']}")
    body = response.json()
    prices = {t["test"]["code"]: t["price"] for t in body["tests"]}
    assert prices == {"CBC": "450.00", "LFT": "999.13"}


async def test_same_test_can_cost_different_amounts_at_different_centres(
    client: AsyncClient, catalogue: dict
) -> None:
    """The reason price lives on the offering rather than on the test."""
    here = await client.get(f"{API}/centres/{catalogue['centre_id']}/tests")
    there = await client.get(f"{API}/centres/{catalogue['other_centre_id']}/tests")
    price_here = next(t["price"] for t in here.json() if t["test"]["code"] == "CBC")
    price_there = next(t["price"] for t in there.json() if t["test"]["code"] == "CBC")
    assert price_here == "450.00"
    assert price_there == "399.00"


async def test_unknown_centre_is_404(client: AsyncClient) -> None:
    response = await client.get(f"{API}/centres/9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "centre_not_found"


async def test_creating_a_centre_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/centres", json={"name": "Rogue", "city": "Nowhere", "address": "Street 1"}
    )
    assert response.status_code == 401


async def test_create_centre_and_offer_a_test(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    created = await client.post(
        f"{API}/centres",
        json={"name": "EVE Jubilee Hills", "city": "Hyderabad", "address": "Road 36"},
        headers=auth,
    )
    assert created.status_code == 201
    centre_id = created.json()["id"]

    offered = await client.post(
        f"{API}/centres/{centre_id}/tests",
        json={"test_id": catalogue["cbc_id"], "price": "525.50"},
        headers=auth,
    )
    assert offered.status_code == 201
    assert offered.json()["price"] == "525.50"


async def test_offering_the_same_test_twice_is_a_conflict(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/centres/{catalogue['centre_id']}/tests",
        json={"test_id": catalogue["cbc_id"], "price": "600.00"},
        headers=auth,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offering_exists"


async def test_offering_for_an_unknown_centre_is_404(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/centres/9999/tests",
        json={"test_id": catalogue["cbc_id"], "price": "100.00"},
        headers=auth,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "centre_not_found"


async def test_offering_an_unknown_test_is_404(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/centres/{catalogue['centre_id']}/tests",
        json={"test_id": 9999, "price": "100.00"},
        headers=auth,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "test_not_found"


async def test_negative_price_is_rejected(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    response = await client.post(
        f"{API}/centres/{catalogue['other_centre_id']}/tests",
        json={"test_id": catalogue["lft_id"], "price": "-1.00"},
        headers=auth,
    )
    assert response.status_code == 422


async def test_price_keeps_two_decimal_places(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    """Money must not round-trip through a float."""
    response = await client.post(
        f"{API}/centres/{catalogue['other_centre_id']}/tests",
        json={"test_id": catalogue["lft_id"], "price": "1234.56"},
        headers=auth,
    )
    assert response.json()["price"] == "1234.56"


async def test_test_codes_are_normalised_and_unique(
    client: AsyncClient, auth: dict, catalogue: dict
) -> None:
    created = await client.post(
        f"{API}/tests", json={"code": "tsh", "name": "Thyroid Stimulating Hormone"},
        headers=auth,
    )
    assert created.json()["code"] == "TSH"

    duplicate = await client.post(
        f"{API}/tests", json={"code": "TSH", "name": "Duplicate"}, headers=auth
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "test_code_taken"


async def test_test_search(client: AsyncClient, catalogue: dict) -> None:
    response = await client.get(f"{API}/tests", params={"search": "blood"})
    assert [t["code"] for t in response.json()["items"]] == ["CBC"]
