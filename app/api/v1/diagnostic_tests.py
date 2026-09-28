"""The diagnostic test catalogue, independent of any centre."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, PaginationDep, SessionDep
from app.schemas.catalog import DiagnosticTestCreate, DiagnosticTestResponse
from app.schemas.common import Page
from app.services import catalog_service

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get(
    "",
    response_model=Page[DiagnosticTestResponse],
    summary="List diagnostic tests",
)
async def list_tests(
    session: SessionDep,
    pagination: PaginationDep,
    search: Annotated[
        str | None, Query(description="Substring match on test name or code.")
    ] = None,
) -> Page[DiagnosticTestResponse]:
    tests, total = await catalog_service.list_tests(
        session, search=search, limit=pagination.limit, offset=pagination.offset
    )
    return Page(
        items=[DiagnosticTestResponse.model_validate(t) for t in tests],
        meta=pagination.meta(total),
    )


@router.post(
    "",
    response_model=DiagnosticTestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a test to the catalogue",
    responses={409: {"description": "Test code already exists"}},
)
async def create_test(
    payload: DiagnosticTestCreate, session: SessionDep, _: CurrentUser
) -> DiagnosticTestResponse:
    test = await catalog_service.create_test(
        session,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        preparation=payload.preparation,
    )
    return DiagnosticTestResponse.model_validate(test)
