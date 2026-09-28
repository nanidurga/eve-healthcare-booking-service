from __future__ import annotations

from datetime import datetime
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
from app.models.enums import BookingStatus
from app.models.mixins import TimestampMixin
from app.models.types import Money, UTCDateTime

if TYPE_CHECKING:
    from app.models.centre_test import CentreTest
    from app.models.payment import Payment
    from app.models.user import User

# A slot is only "taken" while the booking is live; a cancelled or failed
# booking must not block the user from re-booking the same slot.
_ACTIVE_STATUSES_SQL = text("status IN ('PENDING', 'CONFIRMED')")


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        # One live booking per user, per offering, per slot. Enforced by the
        # database so two concurrent requests cannot both succeed.
        Index(
            "uq_bookings_active_slot",
            "user_id",
            "centre_test_id",
            "appointment_at",
            unique=True,
            postgresql_where=_ACTIVE_STATUSES_SQL,
            sqlite_where=_ACTIVE_STATUSES_SQL,
        ),
        Index("ix_bookings_user_created", "user_id", "created_at"),
        CheckConstraint("amount >= 0", name="ck_bookings_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    centre_test_id: Mapped[int] = mapped_column(
        ForeignKey("centre_tests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    appointment_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    # Snapshot of the price at booking time. If the centre re-prices the test
    # tomorrow, what this patient owes must not change.
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)

    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(
            BookingStatus,
            name="booking_status",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=BookingStatus.PENDING,
        nullable=False,
        index=True,
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(back_populates="bookings")
    # Deliberately NOT lazy="joined": the webhook locks booking rows with
    # SELECT ... FOR UPDATE, which PostgreSQL refuses on the nullable side of
    # an outer join. Readers eager-load this explicitly instead.
    centre_test: Mapped[CentreTest] = relationship(back_populates="bookings")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="Payment.id"
    )

    def __repr__(self) -> str:
        return f"<Booking id={self.id} status={self.status} user={self.user_id}>"
