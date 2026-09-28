from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import PaymentStatus
from app.models.mixins import TimestampMixin
from app.models.types import Money

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.webhook_event import WebhookEvent


class Payment(Base, TimestampMixin):
    """A payment attempt against a booking.

    A booking may accumulate several attempts (a failed card, then a retry), so
    this is a one-to-many. Only one may be in flight at a time — see the partial
    unique index below.
    """

    __tablename__ = "payments"
    __table_args__ = (
        # At most one PENDING payment per booking: blocks a double-charge from
        # two concurrent "pay" requests at the database level.
        Index(
            "uq_payments_one_pending_per_booking",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
        CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(
            PaymentStatus,
            name="payment_status",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )
    # The mock provider's own id for this transaction. Webhooks address payments
    # by this value, never by our primary key.
    provider_reference: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="payments")
    webhook_events: Mapped[list[WebhookEvent]] = relationship(back_populates="payment")

    def __repr__(self) -> str:
        return f"<Payment id={self.id} status={self.status} ref={self.provider_reference!r}>"
