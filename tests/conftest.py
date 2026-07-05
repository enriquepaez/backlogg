"""Shared pytest fixtures.

The whole suite runs against ``TEST_DATABASE_URL`` — never against
``DATABASE_URL`` (the main/production database). A safety guard below aborts
the run before any test executes if the isolation cannot be guaranteed.
"""

import os
import re
import sys
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from backlogg.core.config import settings

# ── Safety guard: never touch the main database ──────────────────────────────


def _db_identity(url: str) -> tuple[str | None, str]:
    """Return (host, database name) for a SQLAlchemy-style URL."""
    parts = urlsplit(url)
    return parts.hostname, parts.path


def _enforce_test_db_isolation() -> None:
    test_url = settings.TEST_DATABASE_URL.strip()
    if not test_url:
        pytest.exit(
            "TEST_DATABASE_URL is empty — refusing to run the test suite against "
            "DATABASE_URL. Point TEST_DATABASE_URL to a dedicated test database.",
            returncode=1,
        )
    if _db_identity(test_url) == _db_identity(settings.DATABASE_URL):
        pytest.exit(
            "TEST_DATABASE_URL points to the same database as DATABASE_URL — "
            "refusing to run the test suite against the main database.",
            returncode=1,
        )
    if "backlogg.core.database" in sys.modules:
        pytest.exit(
            "backlogg.core.database was imported before conftest.py could redirect "
            "DATABASE_URL to the test database, so its engine may target the main "
            "database. Nothing may import app modules before this conftest runs.",
            returncode=1,
        )


_enforce_test_db_isolation()

# Redirect every consumer of the settings/environment to the test database.
# backlogg.core.database builds its engine (used by get_db and by the sync
# jobs' async_session_factory) from settings.DATABASE_URL at import time, so
# this override must happen before any app module besides core.config is
# imported — the guard above enforces that ordering.
settings.DATABASE_URL = settings.TEST_DATABASE_URL
os.environ["DATABASE_URL"] = settings.TEST_DATABASE_URL


# ── Database fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def apply_migrations():
    """Apply all Alembic migrations to the test database (session scope).

    alembic/env.py reads DATABASE_URL from the environment (set above to the
    test database) and handles sslmode stripping itself.
    """
    command.upgrade(Config("alembic.ini"), "head")


@pytest_asyncio.fixture(scope="session")
async def db_engine(apply_migrations):
    """Async engine for the test database, session-scoped."""
    url = settings.TEST_DATABASE_URL
    connect_args: dict = {}
    if "sslmode" in url:
        url = re.sub(r"[?&]sslmode=\w+", "", url)
        connect_args["ssl"] = True

    engine = create_async_engine(url, echo=False, connect_args=connect_args)

    # Some code paths commit mid-test (on-demand fallbacks, sync jobs), so the
    # per-test rollback cannot undo everything. Start every suite run from a
    # clean test database to keep results deterministic across runs.
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = [f'"{row[0]}"' for row in result]
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))

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
