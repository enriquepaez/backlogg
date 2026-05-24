import os
import re

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from backlogg.core.config import settings


def _resolve_db_url() -> tuple[str, dict]:
    """Return (clean_url, connect_args) for the test database.

    Uses TEST_DATABASE_URL when explicitly configured.
    Falls back to DATABASE_URL (Neon) when TEST_DATABASE_URL is the default
    localhost placeholder.
    asyncpg does not understand the 'sslmode' query parameter — strip it
    and pass ssl=True via connect_args.
    """
    url = settings.TEST_DATABASE_URL
    if url == "postgresql+asyncpg://localhost/backlogg_test":
        url = settings.DATABASE_URL

    connect_args: dict = {}
    if "sslmode" in url:
        url = re.sub(r"[?&]sslmode=\w+", "", url)
        connect_args["ssl"] = True
    return url, connect_args


@pytest.fixture(scope="session")
def apply_migrations():
    """Apply all Alembic migrations to the test database (session scope)."""
    url, _ = _resolve_db_url()
    alembic_cfg = Config("alembic.ini")

    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url

    command.upgrade(alembic_cfg, "head")

    yield

    if original is not None:
        os.environ["DATABASE_URL"] = original
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]


@pytest_asyncio.fixture(scope="session")
async def db_engine(apply_migrations):
    """Async engine for the test database, session-scoped."""
    url, connect_args = _resolve_db_url()
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncSession:
    """Provide an AsyncSession for each test.

    Each test runs inside a transaction that is rolled back at the end,
    keeping the database clean between tests.

    We rely on SQLAlchemy's autobegin — the first ORM operation starts the
    transaction implicitly.  Calling rollback() at teardown undoes all writes.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
