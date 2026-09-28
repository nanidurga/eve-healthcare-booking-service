"""User registration and login.

Kept out of the router so it can be unit-tested and reused (the seed script
creates a demo user through the same path).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ConflictError
from app.core.security import dummy_verify, hash_password, verify_password
from app.models.user import User


def normalise_email(email: str) -> str:
    """Emails are matched case-insensitively; store one canonical form."""
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User).where(User.email == normalise_email(email))
    )
    return result.scalar_one_or_none()


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None = None,
) -> User:
    user = User(
        email=normalise_email(email),
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        phone=phone,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The unique index is the source of truth. A pre-check SELECT would
        # still race against a concurrent signup with the same address.
        await session.rollback()
        raise ConflictError(
            "An account with this email already exists.", code="email_taken"
        ) from exc
    await session.refresh(user)
    return user


async def authenticate_user(session: AsyncSession, *, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None:
        # Spend the same time as a real verify so this endpoint cannot be used
        # to discover which emails are registered.
        dummy_verify()
        raise AuthenticationError("Incorrect email or password.", code="invalid_credentials")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect email or password.", code="invalid_credentials")
    return user
