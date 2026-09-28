from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.centre_test import CentreTest


class Centre(Base, TimestampMixin):
    """A diagnostic centre. The tests it offers hang off ``CentreTest``."""

    __tablename__ = "centres"
    __table_args__ = (Index("ix_centres_city_name", "city", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(400), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=true(), nullable=False
    )

    centre_tests: Mapped[list[CentreTest]] = relationship(
        back_populates="centre", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Centre id={self.id} name={self.name!r}>"
