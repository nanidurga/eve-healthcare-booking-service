"""Booking endpoints. Every route is scoped to the authenticated user."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.v1.deps import CurrentUser, PaginationDep, SessionDep
from app.models.enums import BookingStatus
from app.schemas.booking import BookingCancel, BookingCreate, BookingResponse
from app.schemas.common import Page
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])

BookingId = Annotated[int, Path(gt=0, description="Booking id")]


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book a diagnostic test",
    responses={
        404: {"description": "Offering not found"},
        409: {"description": "Offering withdrawn, or duplicate booking"},
        422: {"description": "Appointment time is invalid"},
    },
)
async def create_booking(
    payload: BookingCreate, session: SessionDep, current_user: CurrentUser
) -> BookingResponse:
    """Creates a booking in **PENDING**. It is confirmed by paying for it."""
    booking = await booking_service.create_booking(
        session,
        user=current_user,
        centre_test_id=payload.centre_test_id,
        appointment_at=payload.appointment_at,
    )
    return BookingResponse.from_model(booking)


@router.get(
    "",
    response_model=Page[BookingResponse],
    summary="List your bookings",
)
async def list_bookings(
    session: SessionDep,
    current_user: CurrentUser,
    pagination: PaginationDep,
    status_filter: Annotated[
        BookingStatus | None,
        Query(alias="status", description="Only bookings in this state."),
    ] = None,
) -> Page[BookingResponse]:
    bookings, total = await booking_service.list_bookings(
        session,
        user=current_user,
        status=status_filter,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page(
        items=[BookingResponse.from_model(b) for b in bookings],
        meta=pagination.meta(total),
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Get one of your bookings",
    responses={404: {"description": "Booking not found, or not yours"}},
)
async def get_booking(
    booking_id: BookingId, session: SessionDep, current_user: CurrentUser
) -> BookingResponse:
    booking = await booking_service.get_booking(
        session, user=current_user, booking_id=booking_id
    )
    return BookingResponse.from_model(booking)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel a booking",
    responses={
        404: {"description": "Booking not found, or not yours"},
        409: {"description": "Booking is already cancelled"},
    },
)
async def cancel_booking(
    booking_id: BookingId,
    session: SessionDep,
    current_user: CurrentUser,
    payload: BookingCancel | None = None,
) -> BookingResponse:
    booking = await booking_service.cancel_booking(
        session,
        user=current_user,
        booking_id=booking_id,
        reason=payload.reason if payload else None,
    )
    return BookingResponse.from_model(booking)
