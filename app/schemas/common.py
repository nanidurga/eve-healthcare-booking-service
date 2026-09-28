"""Envelopes shared by every endpoint."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Booking 42 was not found."])
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The single error shape returned by every failing endpoint."""

    error: ErrorDetail


class PageMeta(BaseModel):
    total: int = Field(description="Total rows matching the filter, ignoring paging.")
    limit: int
    offset: int
    has_more: bool


class Page(BaseModel, Generic[T]):
    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    meta: PageMeta
