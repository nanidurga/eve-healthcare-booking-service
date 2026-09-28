from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, utcnow
from app.models.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.payment import Payment


class WebhookEvent(Base, TimestampMixin):
    """The idempotency ledger for inbound provider callbacks.

    ``event_id`` is UNIQUE, and inserting it is how a delivery claims the right
    to be processed. Idempotency is therefore enforced by the database rather
    than by a read-then-write check, which would race under concurrent delivery.
    """

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Kept verbatim so a delivery for an unknown payment is still auditable.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # applied | ignored | unknown_payment — what the handler decided to do.
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)

    payment: Mapped[Payment | None] = relationship(back_populates="webhook_events")

    def __repr__(self) -> str:
        return f"<WebhookEvent id={self.id} event_id={self.event_id!r} outcome={self.outcome}>"
