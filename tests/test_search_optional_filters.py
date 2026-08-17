"""Tests for optional ``q`` and date/rating filters on GET /v1/search.

Backend refinement blocking FE-11/FE-35 re-scope (see progress/current.md):
``q`` becomes optional (still ``min_length=1`` when present) and the endpoint
gains ``date_from``/``date_to``/``rating_external_min``/``rating_external_max``
range filters over the ``catalog_search`` materialized view. No
``rating_internal_*`` filter (the view has no such column) and no extra
``search``/substring param (``q`` already covers that).
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backlogg.main import app
from backlogg.movies import repository as movies_repo

_REFRESH_PATCH = "backlogg.search.repository.SearchRepository.refresh_catalog_search"
_INGEST_PATCHES = (
    "backlogg.search.service._ingest_movies",
    "backlogg.search.service._ingest_series",
    "backlogg.search.service._ingest_books",
    "backlogg.search.service._ingest_games",
)


def _movie_dict(slug: str, title: str, rel: date, rext: float) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "x",
        "release_date": rel,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rext,
        "rating_count_external": 10,
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


async def _seed(db, slug: str, title: str, rel: date, rext: float) -> None:
    await movies_repo.upsert_movie(db, _movie_dict(slug, title, rel, rext))


# ── Filters combined, without q (pure filter mode) ──────────────────────────


async def test_search_without_q_filters_by_date_range(client, db):
    await _seed(db, "sof-in-range-2020", "Sof In Range", date(2020, 6, 1), 5.0)
    await _seed(db, "sof-out-range-2015", "Sof Out Of Range", date(2015, 6, 1), 5.0)
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    response = await client.get("/v1/search?date_from=2020-01-01&date_to=2021-12-31&type=movie")
    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "sof-in-range-2020" in slugs
    assert "sof-out-range-2015" not in slugs


async def test_search_without_q_filters_by_rating_external_range(client, db):
    await _seed(db, "sof-high-rated-2020", "Sof High Rated", date(2020, 1, 1), 9.0)
    await _seed(db, "sof-low-rated-2020", "Sof Low Rated", date(2020, 1, 1), 2.0)
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    response = await client.get(
        "/v1/search?rating_external_min=8.0&rating_external_max=10.0&type=movie"
    )
    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "sof-high-rated-2020" in slugs
    assert "sof-low-rated-2020" not in slugs


async def test_search_without_q_orders_by_rating_external_desc(client, db):
    await _seed(db, "sof-order-low-2020", "Sof Order Low", date(2020, 1, 1), 3.0)
    await _seed(db, "sof-order-high-2020", "Sof Order High", date(2020, 1, 1), 8.0)
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    response = await client.get("/v1/search?type=movie")
    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    high_idx = slugs.index("sof-order-high-2020")
    low_idx = slugs.index("sof-order-low-2020")
    assert high_idx < low_idx


# ── Filters combined, with q present (no behaviour regression) ──────────────


async def test_search_with_q_and_date_range_filters_combined(client, db):
    await _seed(db, "sof-q-inrange-2020", "Sof Q Combo Movie", date(2020, 6, 1), 5.0)
    await _seed(db, "sof-q-outrange-2010", "Sof Q Combo Movie", date(2010, 6, 1), 5.0)
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    response = await client.get("/v1/search?q=Sof+Q+Combo&date_from=2018-01-01&date_to=2022-12-31")
    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "sof-q-inrange-2020" in slugs
    assert "sof-q-outrange-2010" not in slugs


async def test_search_with_q_and_rating_external_range_filters_combined(client, db):
    await _seed(db, "sof-q-highrating-2020", "Sof Q Rating Movie", date(2020, 1, 1), 9.0)
    await _seed(db, "sof-q-lowrating-2020", "Sof Q Rating Movie", date(2020, 1, 1), 2.0)
    await db.flush()
    await db.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    response = await client.get(
        "/v1/search?q=Sof+Q+Rating&rating_external_min=8.0&rating_external_max=10.0"
    )
    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "sof-q-highrating-2020" in slugs
    assert "sof-q-lowrating-2020" not in slugs


# ── Invalid ranges → 422 ─────────────────────────────────────────────────────


async def test_search_date_from_after_date_to_returns_422(client, db):
    response = await client.get("/v1/search?date_from=2021-12-31&date_to=2021-01-01")
    assert response.status_code == 422


async def test_search_rating_external_min_greater_than_max_returns_422(client, db):
    response = await client.get("/v1/search?rating_external_min=9&rating_external_max=3")
    assert response.status_code == 422


async def test_search_empty_q_explicit_still_returns_422(client, db):
    """``q=`` explicit (empty string) is still invalid — only an absent q is optional."""
    response = await client.get("/v1/search?q=")
    assert response.status_code == 422


async def test_search_invalid_date_format_returns_422(client, db):
    response = await client.get("/v1/search?date_from=not-a-date")
    assert response.status_code == 422


# ── q absent never triggers the external fan-out ─────────────────────────────


async def test_search_without_q_ingest_and_refresh_mocks_never_called(client, db):
    """Filters alone with 0 local matches must not fan-out — q is required for that."""
    ingest_mocks = [AsyncMock(return_value=None) for _ in _INGEST_PATCHES]
    refresh_mock = AsyncMock(return_value=None)

    with (
        patch(_INGEST_PATCHES[0], new=ingest_mocks[0]),
        patch(_INGEST_PATCHES[1], new=ingest_mocks[1]),
        patch(_INGEST_PATCHES[2], new=ingest_mocks[2]),
        patch(_INGEST_PATCHES[3], new=ingest_mocks[3]),
        patch(_REFRESH_PATCH, new=refresh_mock),
    ):
        response = await client.get("/v1/search?rating_external_min=9.9&rating_external_max=10.0")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    for mock in ingest_mocks:
        mock.assert_not_called()
    refresh_mock.assert_not_called()


async def test_search_without_q_does_not_call_enforce_search_fallback(client, db):
    """The rate-limit gate itself must not be consulted when q is absent."""
    ingest_mocks = [AsyncMock(return_value=None) for _ in _INGEST_PATCHES]
    refresh_mock = AsyncMock(return_value=None)
    enforce_mock = AsyncMock(return_value=None)

    with (
        patch(_INGEST_PATCHES[0], new=ingest_mocks[0]),
        patch(_INGEST_PATCHES[1], new=ingest_mocks[1]),
        patch(_INGEST_PATCHES[2], new=ingest_mocks[2]),
        patch(_INGEST_PATCHES[3], new=ingest_mocks[3]),
        patch(_REFRESH_PATCH, new=refresh_mock),
        patch("backlogg.search.service.enforce_search_fallback", new=enforce_mock),
    ):
        response = await client.get("/v1/search?date_from=2020-01-01")

    assert response.status_code == 200
    enforce_mock.assert_not_called()


# ── Regression: the post-ingest re-query must reapply the active filters ────
#
# Bug: SearchService.search() re-queried the repo after the external fan-out
# without forwarding date_from/date_to/rating_external_min/rating_external_max,
# so a freshly ingested (or already-present) item outside the requested range
# could leak into the final response.


async def test_search_fanout_requery_reapplies_date_filter(client, db):
    """0 local matches for q + date range active -> fan-out fires; the ingest
    inserts two items matching q (one inside the range, one outside); the
    final response must only contain the one inside the range.
    """

    async def fake_ingest_movies(q):
        await _seed(db, "faf-date-inrange-2020", "Faf Date Reapply", date(2020, 6, 1), 5.0)
        await _seed(db, "faf-date-outrange-2010", "Faf Date Reapply", date(2010, 6, 1), 5.0)
        await db.flush()

    async def fake_refresh(self):
        await self._session.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    with (
        patch("backlogg.search.service._ingest_movies", new=fake_ingest_movies),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=fake_refresh),
    ):
        response = await client.get(
            "/v1/search?q=Faf+Date+Reapply&date_from=2018-01-01&date_to=2022-12-31&type=movie"
        )

    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "faf-date-inrange-2020" in slugs
    assert "faf-date-outrange-2010" not in slugs


async def test_search_fanout_requery_reapplies_rating_external_filter(client, db):
    """Same scenario, but with a rating_external range active instead of dates."""

    async def fake_ingest_movies(q):
        await _seed(db, "faf-rating-inrange-2020", "Faf Rating Reapply", date(2020, 1, 1), 9.0)
        await _seed(db, "faf-rating-outrange-2020", "Faf Rating Reapply", date(2020, 1, 1), 2.0)
        await db.flush()

    async def fake_refresh(self):
        await self._session.execute(text("REFRESH MATERIALIZED VIEW catalog_search"))

    with (
        patch("backlogg.search.service._ingest_movies", new=fake_ingest_movies),
        patch("backlogg.search.service._ingest_series", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_books", new=AsyncMock(return_value=None)),
        patch("backlogg.search.service._ingest_games", new=AsyncMock(return_value=None)),
        patch(_REFRESH_PATCH, new=fake_refresh),
    ):
        response = await client.get(
            "/v1/search?q=Faf+Rating+Reapply&rating_external_min=8.0&rating_external_max=10.0&type=movie"
        )

    assert response.status_code == 200
    slugs = [r["slug"] for r in response.json()["results"]]
    assert "faf-rating-inrange-2020" in slugs
    assert "faf-rating-outrange-2020" not in slugs
