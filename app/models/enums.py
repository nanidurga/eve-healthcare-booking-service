"""Enumerations shared by the models, schemas and services."""

from enum import StrEnum


class BookingStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (PaymentStatus.SUCCESS, PaymentStatus.FAILED)
