"""Diagnostic centre and offering endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.v1.deps import CurrentUser, PaginationDep, SessionDep
from app.schemas.catalog import (
    CentreCreate,
    CentreDetailResponse,
    CentreResponse,
    CentreTestCreate,
    CentreTestResponse,
)
from app.schemas.common import Page
from app.services import catalog_service

router = APIRouter(prefix="/centres", tags=["centres"])

CentreId = Annotated[int, Path(gt=0, description="Centre id")]


@router.get(
    "",
    response_model=Page[CentreResponse],
    summary="List diagnostic centres",
)
async def list_centres(
    session: SessionDep,
    pagination: PaginationDep,
    city: Annotated[
        str | None, Query(description="Exact city match, case-insensitive.")
    ] = None,
    test_code: Annotated[
        str | None,
        Query(description="Only centres that actively offer this test code."),
    ] = None,
) -> Page[CentreResponse]:
    """Public: patients need to browse before they have an account."""
    centres, total = await catalog_service.list_centres(
        session,
        city=city,
        test_code=test_code,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page(
        items=[CentreResponse.model_validate(c) for c in centres],
        meta=pagination.meta(total),
    )


@router.post(
    "",
    response_model=CentreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a diagnostic centre",
)
async def create_centre(
    payload: CentreCreate, session: SessionDep, _: CurrentUser
) -> CentreResponse:
    """Requires authentication.

    There is no role model in this assignment, so any authenticated user may
    manage the catalogue. A real deployment would gate this behind an
    operations role -- see "Assumptions" in the README.
    """
    centre = await catalog_service.create_centre(
        session,
        name=payload.name,
        city=payload.city,
        address=payload.address,
        phone=payload.phone,
    )
    return CentreResponse.model_validate(centre)


@router.get(
    "/{centre_id}",
    response_model=CentreDetailResponse,
    summary="Get a centre with the tests it offers",
    responses={404: {"description": "Centre not found"}},
)
async def get_centre(centre_id: CentreId, session: SessionDep) -> CentreDetailResponse:
    centre = await catalog_service.get_centre(session, centre_id)
    active = [ct for ct in centre.centre_tests if ct.is_active]
    return CentreDetailResponse(
        **CentreResponse.model_validate(centre).model_dump(),
        tests=[CentreTestResponse.model_validate(ct) for ct in active],
    )


@router.get(
    "/{centre_id}/tests",
    response_model=list[CentreTestResponse],
    summary="List the tests a centre offers, with prices",
    responses={404: {"description": "Centre not found"}},
)
async def list_centre_tests(
    centre_id: CentreId, session: SessionDep
) -> list[CentreTestResponse]:
    offerings = await catalog_service.list_centre_tests(session, centre_id)
    return [CentreTestResponse.model_validate(o) for o in offerings]


@router.post(
    "/{centre_id}/tests",
    response_model=CentreTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Offer a test at this centre, at a given price",
    responses={
        404: {"description": "Centre or test not found"},
        409: {"description": "Centre already offers this test"},
    },
)
async def add_centre_test(
    centre_id: CentreId,
    payload: CentreTestCreate,
    session: SessionDep,
    _: CurrentUser,
) -> CentreTestResponse:
    offering = await catalog_service.add_centre_test(
        session, centre_id=centre_id, test_id=payload.test_id, price=payload.price
    )
    return CentreTestResponse.model_validate(offering)
