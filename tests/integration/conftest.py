"""Integration fixtures: ephemeral Postgres + per-test transaction isolation.

Strategy
--------
- One Postgres container for the whole session (expensive to spin up). Schema is
  created once, synchronously (psycopg2), so no event loop is involved at setup —
  this keeps every async fixture + the test itself on a single function-scoped loop
  (mixing loop scopes makes asyncpg raise "attached to a different loop"). Swap the
  create_all for an Alembic `upgrade head` if you'd rather test the migrations.
- Each test runs inside an outer transaction that is rolled back at the end, so the
  DB is pristine between tests without recreating the schema. A SAVEPOINT is
  restarted after every service-level commit (the service calls db.commit()), which
  keeps that isolation intact.
- The FastAPI app's get_session dependency is overridden so routes and the test
  share the exact same session/transaction.
"""

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from app.core.database.database import get_session
from app.main import app
from app.models import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_url() -> Generator[str]:
    with PostgresContainer("postgres:18.4") as pg:
        sync_url = pg.get_connection_url()  # psycopg2 driver
        sync_engine = create_engine(sync_url)
        with sync_engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        # The app itself uses asyncpg.
        yield sync_url.replace("psycopg2", "asyncpg")


@pytest_asyncio.fixture
async def engine(pg_url: str):
    eng = create_async_engine(pg_url)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession]:
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    await connection.begin_nested()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sess, trans) -> None:
        # When the service commits, the SAVEPOINT ends — open a new one so the
        # outer transaction (rolled back below) still owns everything.
        if trans.nested and not trans._parent.nested:
            connection.sync_connection.begin_nested()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def _override_get_session() -> AsyncGenerator[AsyncSession]:
        yield db

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


DEFAULT_EMAIL = "user@example.com"
DEFAULT_PASSWORD = "supersecret"


@pytest.fixture
def credentials() -> dict[str, str]:
    return {"email": DEFAULT_EMAIL, "password": DEFAULT_PASSWORD}


@pytest_asyncio.fixture
async def registered(client: AsyncClient, credentials: dict[str, str]) -> dict[str, object]:
    """Register the default user and return the response body.

    Leaves the refresh-token cookie in the client's jar, so authed requests
    (refresh, logout) work without re-sending it manually.
    """
    resp = await client.post("/auth/register", json=credentials)
    assert resp.status_code == 201
    return resp.json()
