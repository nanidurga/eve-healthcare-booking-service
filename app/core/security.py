"""Password hashing and JWT issue/verify.

Uses ``bcrypt`` directly rather than passlib: passlib is unmaintained against
bcrypt 4.x and emits a spurious ``__about__`` error on import.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AuthenticationError

# bcrypt hashes at most 72 bytes of input and raises above that. Schemas enforce
# the same bound so a long password fails validation (422) instead of blowing up.
MAX_PASSWORD_BYTES = 72

# A pre-computed hash of a throwaway value. Verifying against it when the user
# does not exist keeps login timing constant, so the endpoint cannot be used to
# enumerate registered email addresses.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    ).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def dummy_verify() -> None:
    """Burn the same time a real verify would, for non-existent users."""
    bcrypt.checkpw(b"dummy-password-for-timing", _DUMMY_HASH.encode("utf-8"))


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expire = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token, or raise ``AuthenticationError``."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Access token is invalid.", code="token_invalid") from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Token is not an access token.", code="token_invalid")
    return payload
