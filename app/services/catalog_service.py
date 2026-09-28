"""Reads and writes over the centre / test catalogue."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.models.centre import Centre
from app.models.centre_test import CentreTest
from app.models.diagnostic_test import DiagnosticTest


async def count_rows(session: AsyncSession, stmt: Select) -> int:
    """Total rows matching a filtered query, ignoring ordering and paging."""
    subquery = stmt.order_by(None).subquery()
    return await session.scalar(select(func.count()).select_from(subquery)) or 0


# ---------------------------------------------------------------------------
# Diagnostic tests
# ---------------------------------------------------------------------------
async def list_tests(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[DiagnosticTest], int]:
    stmt = select(DiagnosticTest)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(DiagnosticTest.name).like(pattern)
            | func.lower(DiagnosticTest.code).like(pattern)
        )
    total = await count_rows(session, stmt)
    rows = await session.scalars(
        stmt.order_by(DiagnosticTest.name).limit(limit).offset(offset)
    )
    return list(rows), total


async def create_test(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    description: str | None,
    preparation: str | None,
) -> DiagnosticTest:
    normalised_code = code.strip().upper()
    test = DiagnosticTest(
        code=normalised_code,
        name=name.strip(),
        description=description,
        preparation=preparation,
    )
    session.add(test)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            f"A diagnostic test with code {normalised_code} already exists.",
            code="test_code_taken",
        ) from exc
    await session.refresh(test)
    return test


# ---------------------------------------------------------------------------
# Centres
# ---------------------------------------------------------------------------
async def list_centres(
    session: AsyncSession,
    *,
    city: str | None,
    test_code: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Centre], int]:
    stmt = select(Centre).where(Centre.is_active.is_(True))
    if city:
        stmt = stmt.where(func.lower(Centre.city) == city.strip().lower())
    if test_code:
        # "Which centres offer this test?" -- an EXISTS keeps centre rows
        # distinct without a DISTINCT over the whole joined row.
        offering = (
            select(CentreTest.id)
            .join(DiagnosticTest, DiagnosticTest.id == CentreTest.test_id)
            .where(
                CentreTest.centre_id == Centre.id,
                CentreTest.is_active.is_(True),
                func.lower(DiagnosticTest.code) == test_code.strip().lower(),
            )
        )
        stmt = stmt.where(offering.exists())

    total = await count_rows(session, stmt)
    rows = await session.scalars(
        stmt.order_by(Centre.city, Centre.name).limit(limit).offset(offset)
    )
    return list(rows), total


async def get_centre(session: AsyncSession, centre_id: int) -> Centre:
    stmt = (
        select(Centre)
        .where(Centre.id == centre_id)
        .options(selectinload(Centre.centre_tests).selectinload(CentreTest.test))
    )
    centre = (await session.execute(stmt)).unique().scalar_one_or_none()
    if centre is None:
        raise NotFoundError(
            f"Centre {centre_id} was not found.", code="centre_not_found"
        )
    return centre


async def create_centre(
    session: AsyncSession, *, name: str, city: str, address: str, phone: str | None
) -> Centre:
    centre = Centre(
        name=name.strip(), city=city.strip(), address=address.strip(), phone=phone
    )
    session.add(centre)
    await session.commit()
    await session.refresh(centre)
    return centre


# ---------------------------------------------------------------------------
# Offerings (centre + test + price)
# ---------------------------------------------------------------------------
async def list_centre_tests(session: AsyncSession, centre_id: int) -> list[CentreTest]:
    await get_centre(session, centre_id)  # 404 for an unknown centre
    rows = await session.scalars(
        select(CentreTest)
        .where(CentreTest.centre_id == centre_id, CentreTest.is_active.is_(True))
        .order_by(CentreTest.id)
    )
    return list(rows.unique())


async def add_centre_test(
    session: AsyncSession, *, centre_id: int, test_id: int, price: Decimal
) -> CentreTest:
    await get_centre(session, centre_id)
    if await session.get(DiagnosticTest, test_id) is None:
        raise NotFoundError(
            f"Diagnostic test {test_id} was not found.", code="test_not_found"
        )

    offering = CentreTest(centre_id=centre_id, test_id=test_id, price=price)
    session.add(offering)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "This centre already offers that test; update the existing offering.",
            code="offering_exists",
        ) from exc
    await session.refresh(offering)
    return offering


async def get_bookable_offering(
    session: AsyncSession, centre_test_id: int
) -> CentreTest:
    """Resolve the offering a booking names, or explain why it is not bookable."""
    offering = await session.get(CentreTest, centre_test_id)
    if offering is None:
        raise NotFoundError(
            f"Offering {centre_test_id} was not found.", code="offering_not_found"
        )
    if not offering.is_active or not offering.centre.is_active:
        raise ConflictError(
            "This test is no longer offered at the selected centre.",
            code="offering_inactive",
        )
    return offering
