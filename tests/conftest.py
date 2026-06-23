import os
import re

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from backlogg.core.config import settings


@pytest.fixture(scope="session")
def apply_migrations():
    """Apply all Alembic migrations to the test database (session scope)."""
    alembic_cfg = Config("alembic.ini")

    # Pass DATABASE_URL as-is so Alembic's env.py can handle sslmode stripping.
    raw_url = settings.DATABASE_URL
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = raw_url

    command.upgrade(alembic_cfg, "head")

    yield

    if original is not None:
        os.environ["DATABASE_URL"] = original
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]


@pytest_asyncio.fixture(scope="session")
async def db_engine(apply_migrations):
    """Async engine for the test database, session-scoped."""
    url = settings.DATABASE_URL
    connect_args: dict = {}
    if "sslmode" in url:
        url = re.sub(r"[?&]sslmode=\w+", "", url)
        connect_args["ssl"] = True

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
