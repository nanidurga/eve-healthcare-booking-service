"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_salted_and_verifies() -> None:
    first = hash_password("password123")
    second = hash_password("password123")
    assert first != second, "each hash must use a fresh salt"
    assert verify_password("password123", first)
    assert verify_password("password123", second)


def test_wrong_password_does_not_verify() -> None:
    assert not verify_password("wrong", hash_password("password123"))


def test_verify_tolerates_a_corrupt_hash() -> None:
    """A malformed stored hash must be a failed login, not a 500."""
    assert not verify_password("password123", "not-a-bcrypt-hash")


def test_round_trip_carries_the_subject() -> None:
    payload = decode_access_token(create_access_token(42))
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_expired_token_is_rejected() -> None:
    token = create_access_token(1, expires_delta=timedelta(seconds=-10))
    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token)
    assert excinfo.value.code == "token_expired"


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(1)
    head, body, signature = token.split(".")
    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(f"{head}.{body}.{signature[:-4]}abcd")
    assert excinfo.value.code == "token_invalid"


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "1", "exp": 9_999_999_999, "type": "access"},
        "a-different-secret-entirely-but-long-enough-for-hs256",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forged)


def test_non_access_token_is_rejected() -> None:
    """A refresh token must not be usable as an access token."""
    refresh = jwt.encode(
        {"sub": "1", "exp": 9_999_999_999, "type": "refresh"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(refresh)
    assert excinfo.value.code == "token_invalid"


def test_token_without_expiry_is_rejected() -> None:
    forever = jwt.encode(
        {"sub": "1", "type": "access"}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(forever)


def test_garbage_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("clearly-not-a-token")
