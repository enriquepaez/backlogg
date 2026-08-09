"""Tests for GET /admin/stats endpoint."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app

_VALID_KEY = "test-admin-secret"


@pytest_asyncio.fixture
async def client():
    """AsyncClient wired to the FastAPI app with a valid API key configured."""
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── Helpers ────────────────────────────────────────────────────────────────────

_TS = datetime(2026, 5, 25, 3, 0, 0, tzinfo=UTC)


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_stats_returns_200(client):
    """GET /admin/stats returns 200."""
    response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 200


async def test_stats_response_has_all_types(client):
    """GET /admin/stats response contains all 4 content types."""
    response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    body = response.json()
    assert "movies" in body
    assert "series" in body
    assert "books" in body
    assert "games" in body


async def test_stats_response_structure(client):
    """Each content type has count and last_synced_at keys."""
    response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    body = response.json()
    for key in ("movies", "series", "books", "games"):
        assert "count" in body[key], f"{key} missing 'count'"
        assert "last_synced_at" in body[key], f"{key} missing 'last_synced_at'"


async def test_stats_count_is_integer(client):
    """count is always an integer (not null, not string)."""
    response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 200
    body = response.json()
    for key in ("movies", "series", "books", "games"):
        assert isinstance(body[key]["count"], int), f"{key}.count must be int"


async def test_stats_returns_correct_values_from_db(client):
    """GET /admin/stats returns counts and timestamps from DB queries.

    Patches get_db to inject a controlled AsyncSession that returns
    preset (count, last_synced_at) rows — verifies that the endpoint
    maps these values to the response correctly.
    """
    _TS_STR = "2026-05-25T03:00:00Z"

    # row objects: row[0] = count, row[1] = timestamp
    def _make_row(count, ts):
        row = MagicMock()
        row.__getitem__ = lambda self, idx, _c=count, _t=ts: _c if idx == 0 else _t
        return row

    rows = [
        _make_row(120, _TS),  # movies
        _make_row(85, _TS),  # series
        _make_row(200, _TS),  # books
        _make_row(60, None),  # games — null timestamp
    ]
    results = [MagicMock(one=MagicMock(return_value=r)) for r in rows]

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(side_effect=results)

    async def override_get_db():
        yield fake_db

    from backlogg.core.database import get_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["movies"]["count"] == 120
    assert body["series"]["count"] == 85
    assert body["books"]["count"] == 200
    assert body["games"]["count"] == 60
    assert body["games"]["last_synced_at"] is None


async def test_stats_last_synced_at_can_be_null(client):
    """last_synced_at is null when there is no data for a type.

    We can't guarantee any table is empty in CI, so we only check that
    null is an acceptable value type (no schema validation error).
    The response must be 200 regardless.
    """
    response = await client.get("/v1/admin/stats", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 200
    body = response.json()
    for key in ("movies", "series", "books", "games"):
        # last_synced_at may be a string (ISO datetime) or null — both are valid
        assert body[key]["last_synced_at"] is None or isinstance(body[key]["last_synced_at"], str)
