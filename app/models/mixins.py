"""Reusable model mixins."""

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.types import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    """``created_at`` / ``updated_at``, maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now(), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        server_default=func.now(),
        default=utcnow,
        onupdate=utcnow,
    )
