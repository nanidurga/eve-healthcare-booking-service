"""Shared test fixtures.

Every test gets its own SQLite database file, so tests are fully isolated and
can run without a database server. A file (rather than ``:memory:``) is used
deliberately: the concurrency tests open several connections at once, which a
shared in-memory database cannot support.

Environment variables are set before the application is imported, because
settings are read once at import time.
"""

from __future__ import annotations

import os

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-long-enough-for-hs256-abcdefgh"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["BCRYPT_ROUNDS"] = "4"  # keep hashing out of the critical path
os.environ["PAYMENT_FAILURE_CENTS"] = "13"
os.environ["WEBHOOK_SECRET"] = ""

from collections.abc import AsyncGenerator  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.centre import Centre  # noqa: E402
from app.models.centre_test import CentreTest  # noqa: E402
from app.models.diagnostic_test import DiagnosticTest  # noqa: E402

API = "/api/v1"


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncGenerator[AsyncEngine, None]:
    db_file = tmp_path / "test.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")

    @event.listens_for(test_engine.sync_engine, "connect")
    def _fk_on(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """A session for tests that talk to the service layer directly."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client wired to the real app, backed by the test database."""

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        session = session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------
async def register(client: AsyncClient, email: str, name: str = "Test User") -> dict:
    response = await client.post(
        f"{API}/auth/signup",
        json={"email": email, "password": "password123", "full_name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
        "token": body["access_token"],
    }


@pytest_asyncio.fixture
async def asha(client: AsyncClient) -> dict:
    return await register(client, "asha@example.com", "Asha Verma")


@pytest_asyncio.fixture
async def rahul(client: AsyncClient) -> dict:
    """A second account, for authorisation tests."""
    return await register(client, "rahul@example.com", "Rahul Nair")


@pytest_asyncio.fixture
def auth(asha: dict) -> dict:
    return asha["headers"]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def catalogue(db: AsyncSession) -> dict:
    """Two centres and two offerings, inserted directly for speed.

    ``offering`` is priced normally; ``declining_offering`` ends in .13, which
    the simulated gateway is configured to decline.
    """
    centre = Centre(name="EVE Banjara Hills", city="Hyderabad", address="Road No. 12")
    other_centre = Centre(name="EVE Koramangala", city="Bengaluru", address="80 Feet Rd")
    cbc = DiagnosticTest(code="CBC", name="Complete Blood Count")
    lft = DiagnosticTest(code="LFT", name="Liver Function Test")
    db.add_all([centre, other_centre, cbc, lft])
    await db.flush()

    offering = CentreTest(centre_id=centre.id, test_id=cbc.id, price=Decimal("450.00"))
    declining = CentreTest(centre_id=centre.id, test_id=lft.id, price=Decimal("999.13"))
    remote = CentreTest(
        centre_id=other_centre.id, test_id=cbc.id, price=Decimal("399.00")
    )
    db.add_all([offering, declining, remote])
    await db.commit()

    return {
        "centre_id": centre.id,
        "other_centre_id": other_centre.id,
        "cbc_id": cbc.id,
        "lft_id": lft.id,
        "offering_id": offering.id,
        "declining_offering_id": declining.id,
        "remote_offering_id": remote.id,
    }


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def future(days: int = 3, hours: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(days=days, hours=hours)).isoformat()


def past(days: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@pytest_asyncio.fixture
async def booking(client: AsyncClient, auth: dict, catalogue: dict) -> dict:
    """A PENDING booking for Asha, at the normally-priced offering."""
    response = await client.post(
        f"{API}/bookings",
        json={"centre_test_id": catalogue["offering_id"], "appointment_at": future()},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def api() -> str:
    return API
