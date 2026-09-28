from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.centre_test import CentreTest


class DiagnosticTest(Base, TimestampMixin):
    """The catalogue entry for a test, independent of who offers it.

    Deliberately carries no price: the same test costs different amounts at
    different centres, so price belongs to the centre/test relationship.
    """

    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    preparation: Mapped[str | None] = mapped_column(Text, nullable=True)

    centre_tests: Mapped[list[CentreTest]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DiagnosticTest id={self.id} code={self.code!r}>"
