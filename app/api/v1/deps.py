"""Shared FastAPI dependencies: the DB session, the current user, paging."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AuthenticationError
from app.core.security import decode_access_token
from app.models.user import User
from app.schemas.common import PageMeta

# auto_error=False so a missing header raises our own AuthenticationError and
# renders in the standard error envelope, rather than FastAPI's bare detail.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authorization header is missing.", code="token_missing")

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Token subject is invalid.", code="token_invalid") from exc

    user = await session.get(User, user_id)
    if user is None:
        # Valid signature, but the account is gone (deleted since issue).
        raise AuthenticationError("Account no longer exists.", code="token_invalid")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


class Pagination:
    """Offset/limit paging, bounded so a client cannot ask for the whole table."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100, description="Max rows to return.")] = 20,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset

    def meta(self, total: int) -> PageMeta:
        return PageMeta(
            total=total,
            limit=self.limit,
            offset=self.offset,
            has_more=self.offset + self.limit < total,
        )


PaginationDep = Annotated[Pagination, Depends(Pagination)]
