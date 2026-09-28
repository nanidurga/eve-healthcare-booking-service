"""Integration tests for the authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import API

SIGNUP = {"email": "new@example.com", "password": "password123", "full_name": "New User"}


async def test_signup_returns_a_usable_token(client: AsyncClient) -> None:
    response = await client.post(f"{API}/auth/signup", json=SIGNUP)
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "new@example.com"

    me = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


async def test_signup_never_returns_the_password_hash(client: AsyncClient) -> None:
    response = await client.post(f"{API}/auth/signup", json=SIGNUP)
    assert "password" not in response.text.lower().replace("password123", "")


async def test_duplicate_email_is_a_conflict(client: AsyncClient) -> None:
    await client.post(f"{API}/auth/signup", json=SIGNUP)
    response = await client.post(f"{API}/auth/signup", json=SIGNUP)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_email_uniqueness_ignores_case(client: AsyncClient) -> None:
    await client.post(f"{API}/auth/signup", json=SIGNUP)
    response = await client.post(
        f"{API}/auth/signup", json={**SIGNUP, "email": "NEW@Example.COM"}
    )
    assert response.status_code == 409


async def test_login_is_case_insensitive_on_email(client: AsyncClient) -> None:
    await client.post(f"{API}/auth/signup", json=SIGNUP)
    response = await client.post(
        f"{API}/auth/login", json={"email": "NEW@EXAMPLE.COM", "password": "password123"}
    )
    assert response.status_code == 200


async def test_login_with_a_wrong_password_is_401(client: AsyncClient) -> None:
    await client.post(f"{API}/auth/signup", json=SIGNUP)
    response = await client.post(
        f"{API}/auth/login", json={"email": SIGNUP["email"], "password": "not-it"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_for_an_unknown_email_is_401_not_404(client: AsyncClient) -> None:
    """A 404 would tell an attacker which addresses are registered."""
    response = await client.post(
        f"{API}/auth/login", json={"email": "ghost@example.com", "password": "password123"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_does_not_apply_the_signup_password_policy(client: AsyncClient) -> None:
    """A too-short guess must be a plain 401, not a 422 that leaks the policy."""
    response = await client.post(
        f"{API}/auth/login", json={"email": "ghost@example.com", "password": "short"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({**SIGNUP, "email": "not-an-email"}, "email"),
        ({**SIGNUP, "password": "short"}, "password"),
        ({**SIGNUP, "full_name": ""}, "full_name"),
        ({**SIGNUP, "password": "x" * 73}, "password"),
    ],
)
async def test_signup_validation(client: AsyncClient, payload, field) -> None:
    response = await client.post(f"{API}/auth/signup", json=payload)
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any(f["field"] == field for f in body["details"]["fields"])


async def test_missing_required_fields_is_422(client: AsyncClient) -> None:
    response = await client.post(f"{API}/auth/signup", json={})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ],
)
async def test_me_rejects_bad_credentials(client: AsyncClient, headers) -> None:
    response = await client.get(f"{API}/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"].startswith("token_")


async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
