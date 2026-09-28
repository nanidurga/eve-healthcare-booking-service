from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.types import Money

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.centre import Centre
    from app.models.diagnostic_test import DiagnosticTest


class CentreTest(Base, TimestampMixin):
    """A test offered by a centre, at that centre's price.

    This is the thing a user actually books, which is why ``Booking`` holds a
    single FK to it rather than separate centre and test FKs — one column cannot
    describe a test/centre pairing that does not exist.
    """

    __tablename__ = "centre_tests"
    __table_args__ = (
        UniqueConstraint("centre_id", "test_id", name="uq_centre_tests_centre_test"),
        CheckConstraint("price >= 0", name="ck_centre_tests_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("centres.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=true(), nullable=False
    )

    centre: Mapped[Centre] = relationship(back_populates="centre_tests", lazy="joined")
    test: Mapped[DiagnosticTest] = relationship(back_populates="centre_tests", lazy="joined")
    bookings: Mapped[list[Booking]] = relationship(back_populates="centre_test")

    def __repr__(self) -> str:
        return f"<CentreTest id={self.id} centre={self.centre_id} test={self.test_id}>"
