"""Portable column types.

The service targets PostgreSQL, but the suite also runs on SQLite so the project
can be exercised without a database server. These two decorators absorb the only
behavioural differences that matter here: money precision and timezone handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, TypeDecorator


class Money(TypeDecorator):
    """A currency amount, always handed to the application as ``Decimal``.

    PostgreSQL gets a real ``NUMERIC(12, 2)``. SQLite has no exact decimal type
    and would silently round-trip through ``float``, so the value is stored as a
    fixed-format string instead — lexicographically ordered the same as
    numerically, and exact.
    """

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(20))
        return dialect.type_descriptor(Numeric(12, 2))

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        quantised = Decimal(str(value)).quantize(Decimal("0.01"))
        if dialect.name == "sqlite":
            return f"{quantised:016.2f}"
        return quantised

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        return Decimal(str(value)).quantize(Decimal("0.01"))


class UTCDateTime(TypeDecorator):
    """A timezone-aware timestamp that is always stored and returned in UTC.

    SQLite drops tzinfo entirely; PostgreSQL converts to the session zone. Both
    are normalised here so the application only ever sees aware UTC datetimes.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not accepted; supply a timezone.")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
