"""``sync_cursors`` is gone — table, model, repository and response field.

The table held one offset per item type for the nightly slice.  Every type left
that mechanism for the refresh rotation (movies and series in feature 86, games
in 90, books in issue #27), so by the time migration ``0040`` runs nothing reads
or writes it.  What is asserted here is that the removal is *complete*, which is
the whole point of dropping a dead table: a leftover model or repository helper
is exactly what lets someone wire a cursor back in by accident.

1. **The table does not exist** after migrating to head.
2. **No ORM model maps it**, and ``SyncCursor`` is not importable.
3. **The scheduler repository has no cursor accessors** left.
4. **The API contract has no ``offset``**: the field was a constant 0 whose
   only remaining justification was that ``SyncResponse`` declared it required,
   so it goes with the table rather than outliving it as a lie.

That the *jobs* keep no cursor is asserted where each job lives
(``test_tmdb_discover_seeding.py``, ``test_igdb_targets_seeding.py``,
``test_sync_books_refresh.py``).
"""

from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backlogg.admin.schemas import SyncResponse
from backlogg.core.database import Base
from backlogg.main import app
from backlogg.scheduler import repository as scheduler_repository
from backlogg.shared import models as shared_models

_ADMIN_KEY = "drop-sync-cursors-key"


@pytest_asyncio.fixture
async def admin_client():
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _ADMIN_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── 1. The table ─────────────────────────────────────────────────────────────


async def test_the_sync_cursors_table_does_not_exist(db):
    """Migration 0040 dropped it, and the test DB is migrated to head."""
    result = await db.execute(text("SELECT to_regclass('public.sync_cursors')"))
    assert result.scalar_one() is None


# ── 2. The model ─────────────────────────────────────────────────────────────


def test_no_orm_model_maps_sync_cursors():
    """A mapped class would recreate the table in any ``create_all`` path."""
    assert "sync_cursors" not in Base.metadata.tables
    assert not hasattr(shared_models, "SyncCursor")
    assert "SyncCursor" not in shared_models.__all__


# ── 3. The repository ────────────────────────────────────────────────────────


def test_the_scheduler_repository_has_no_cursor_accessors():
    """``get_sync_offset``/``set_sync_offset`` went with the table."""
    assert not hasattr(scheduler_repository, "get_sync_offset")
    assert not hasattr(scheduler_repository, "set_sync_offset")
    assert not any("sync_offset" in name for name in scheduler_repository.__all__)


# ── 4. The API contract ──────────────────────────────────────────────────────


def test_sync_response_declares_no_offset():
    assert "offset" not in SyncResponse.model_fields


async def test_the_sync_endpoint_returns_no_offset(admin_client):
    """The 200 body of ``POST /admin/sync/{type}`` carries no ``offset`` key."""
    result = {
        "synced": 3,
        "errors": 0,
        "people_errors": 0,
        "skipped_links": 0,
        "skipped_identities": 0,
        "duration_s": 0.2,
        "pending": 0,
        "stuck": 0,
        "refreshed": 3,
    }
    with patch.dict(
        "backlogg.admin.router._SYNC_HANDLERS", {"movie": AsyncMock(return_value=result)}
    ):
        response = await admin_client.post(
            "/v1/admin/sync/movie", headers={"X-API-Key": _ADMIN_KEY}
        )

    assert response.status_code == 200
    body = response.json()
    assert "offset" not in body
    assert body["synced"] == 3
