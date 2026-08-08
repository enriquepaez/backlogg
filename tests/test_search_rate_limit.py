"""Rate limiting tests for the external fallback of GET /search."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backlogg.core import config
from backlogg.main import app
from backlogg.movies import repository as movies_repo

_REFRESH_PATCH = "backlogg.search.repository.SearchRepository.refresh_catalog_search"
_NO_LOCAL = "zzzzzzzzzz_no_local_match_rl"


def _movie_dict(slug: str) -> dict:
    return {
        "title": "Inception",
        "original_title": "Inception",
        "slug": slug,
        "overview": "A thief who steals corporate secrets.",
        "release_date": date(2010, 7, 16),
        "runtime": 148,
        "original_language": "en",
        "poster_url": "https://example.com/inception.jpg",
        "backdrop_url": None,
        "budget": 160000000,
        "revenue": 836836967,
        "status": "Released",
        "rating_external": 8.4,
        "rating_count_external": 30000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _fallback_patches():
    return (
        patch("backlogg.search.service._ingest_movies", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=AsyncMock(return_value=None)),
    )


async def test_search_fallback_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_SEARCH_FALLBACK", "2/60")
    p1, p2, p3, p4, p5 = _fallback_patches()
    with p1, p2, p3, p4, p5:
        # Two misses trigger the fan-out and consume quota.
        for _ in range(2):
            resp = await client.get(f"/search?q={_NO_LOCAL}")
            assert resp.status_code == 200
        # The third miss from the same IP is rejected before any external call.
        resp = await client.get(f"/search?q={_NO_LOCAL}")
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["detail"] == "Too many requests. Please try again later."


async def test_search_with_local_results_does_not_consume_quota(client, db, monkeypatch):
    """A query served from the local catalog never consumes the fallback quota."""
    monkeypatch.setattr(config.settings, "RATE_LIMIT_SEARCH_FALLBACK", "2/60")
    await movies_repo.upsert_movie(db, _movie_dict("inception-2010-rl-test"))
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    p1, p2, p3, p4, p5 = _fallback_patches()
    with p1, p2, p3, p4, p5:
        # Many local-hit queries — well beyond the fallback limit of 2.
        for _ in range(5):
            resp = await client.get("/search?q=inception")
            assert resp.status_code == 200
            assert resp.json()["total"] > 0
