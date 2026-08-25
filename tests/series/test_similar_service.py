"""Tests for get_similar_series service function."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.series import repository as repo
from backlogg.series import service
from backlogg.shared.external_ids import upsert_external_id

# Fake TMDB IDs that do NOT correspond to real series
# Use very high numbers to avoid clashing with the real DB
_SOURCE_TMDB_ID_SIM = "9999801"
_SOURCE_TMDB_ID_LOCAL = "9999802"
_SOURCE_TMDB_ID_LIMIT = "9999803"
_REC_TMDB_ID = 9999810


def _make_source_series_dict(slug: str) -> dict:
    return {
        "title": "Fake Source Series",
        "original_title": "Fake Source Series",
        "slug": slug,
        "overview": "A test series.",
        "first_air_date": date(2008, 1, 20),
        "last_air_date": date(2013, 9, 29),
        "number_of_seasons": 5,
        "number_of_episodes": 62,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 9.0,
        "rating_count_external": 5000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _make_tmdb_series_detail(tmdb_id: int = _REC_TMDB_ID) -> dict:
    return {
        "id": tmdb_id,
        "name": "Recommended Series",
        "original_name": "Recommended Series",
        "overview": "A recommended show.",
        "first_air_date": "2015-02-08",
        "last_air_date": "2022-08-15",
        "number_of_seasons": 6,
        "number_of_episodes": 63,
        "status": "Ended",
        "original_language": "en",
        "poster_path": "/rec.jpg",
        "backdrop_path": None,
        "vote_average": 8.8,
        "vote_count": 5000,
        "genres": [{"id": 18, "name": "Drama"}],
        "created_by": [],
    }


def _make_recommendation_item(tmdb_id: int = _REC_TMDB_ID) -> dict:
    """Minimal item as returned by the TMDB TV recommendations list endpoint."""
    return {
        "id": tmdb_id,
        "name": "Recommended Series",
        "first_air_date": "2015-02-08",
        "poster_path": "/rec.jpg",
        "vote_average": 8.8,
        "vote_count": 5000,
    }


async def test_get_similar_series_404_for_unknown_slug(db):
    """Returns 404 when the source series does not exist in DB."""
    with pytest.raises(HTTPException) as exc_info:
        await service.get_similar_series(db, "slug-that-does-not-exist-similar-series-xyz")
    assert exc_info.value.status_code == 404


async def test_get_similar_series_empty_when_no_tmdb_id(db):
    """Returns empty results when series has no TMDB external ID."""
    await repo.upsert_series(db, _make_source_series_dict("similar-series-test-no-tmdb-2008"))
    # No external ID inserted — simulates a locally-only entry

    result = await service.get_similar_series(db, "similar-series-test-no-tmdb-2008")

    assert result.results == []


async def test_get_similar_series_persists_and_returns(db):
    """Recommendations not in DB are fetched, persisted, and returned."""
    series = await repo.upsert_series(
        db, _make_source_series_dict("similar-series-test-source-sim-2008")
    )
    await upsert_external_id(db, "SERIES", series.id, "TMDB", _SOURCE_TMDB_ID_SIM)

    rec_item = _make_recommendation_item(tmdb_id=_REC_TMDB_ID)
    rec_detail = _make_tmdb_series_detail(tmdb_id=_REC_TMDB_ID)

    with (
        patch.object(
            service._tmdb,
            "get_series_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(
            service._tmdb,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=rec_detail,
        ),
    ):
        result = await service.get_similar_series(db, "similar-series-test-source-sim-2008")

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Recommended Series"
    assert item.slug == "recommended-series-2015"
    assert item.poster_url is not None
    assert item.release_date == date(2015, 2, 8)
    assert item.rating_external == 8.8

    # Verify it was persisted
    persisted = await repo.get_series_by_slug(db, "recommended-series-2015")
    assert persisted is not None


async def test_get_similar_series_uses_local_if_already_present(db):
    """Items already in DB are used without calling get_series_detail."""
    series = await repo.upsert_series(
        db, _make_source_series_dict("similar-series-test-source-local-2008")
    )
    await upsert_external_id(db, "SERIES", series.id, "TMDB", _SOURCE_TMDB_ID_LOCAL)

    # Pre-seed the recommended series in DB
    rec_dict = {
        "title": "Recommended Series Local",
        "original_title": "Recommended Series Local",
        "slug": "recommended-series-local-2015",
        "overview": "A recommended show already in DB.",
        "first_air_date": date(2015, 2, 8),
        "last_air_date": date(2022, 8, 15),
        "number_of_seasons": 6,
        "number_of_episodes": 63,
        "status": "Ended",
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/rec.jpg",
        "backdrop_url": None,
        "rating_external": 8.8,
        "rating_count_external": 5000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }
    await repo.upsert_series(db, rec_dict)

    # recommendation item name + date -> "recommended-series-local-2015"
    rec_item = {
        "id": _REC_TMDB_ID + 1,
        "name": "Recommended Series Local",
        "first_air_date": "2015-02-08",
    }

    with (
        patch.object(
            service._tmdb,
            "get_series_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(service._tmdb, "get_series_detail", new_callable=AsyncMock) as mock_detail,
    ):
        result = await service.get_similar_series(db, "similar-series-test-source-local-2008")

    mock_detail.assert_not_called()
    assert len(result.results) == 1
    assert result.results[0].slug == "recommended-series-local-2015"


# ── Feature 66: rating_display_internal_only ────────────────────────────────


async def test_get_similar_series_orders_by_rating_internal_over_external(db):
    """Results are re-ordered by rating_internal desc, not TMDB's own order.

    TMDB's recommendations list the low-rating_internal series first — the
    response must still surface the high-rating_internal series first, even
    though it has a lower rating_external.
    """
    series = await repo.upsert_series(
        db, _make_source_series_dict("similar-series-test-source-order-2008")
    )
    await upsert_external_id(db, "SERIES", series.id, "TMDB", "9999804")

    # Pre-seed both candidates locally with an already-computed rating_internal
    # (feature 62) so the ranking signal comes from the persisted local row.
    low_internal_high_external = {
        "title": "Similar Series Order Low Internal",
        "original_title": "Similar Series Order Low Internal",
        "slug": "similar-series-order-low-internal-2015",
        "overview": "",
        "first_air_date": date(2015, 2, 8),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 9.5,
        "rating_count_external": 5000,
        "rating_internal": 2.0,
        "rating_count_internal": 3,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }
    high_internal_low_external = {
        "title": "Similar Series Order High Internal",
        "original_title": "Similar Series Order High Internal",
        "slug": "similar-series-order-high-internal-2016",
        "overview": "",
        "first_air_date": date(2016, 3, 1),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 1.0,
        "rating_count_external": 5000,
        "rating_internal": 4.5,
        "rating_count_internal": 8,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }
    await repo.upsert_series(db, low_internal_high_external)
    await repo.upsert_series(db, high_internal_low_external)

    # TMDB's own recommendations order lists the low-rating_internal series first.
    rec_items = [
        {
            "id": 9999960,
            "name": "Similar Series Order Low Internal",
            "first_air_date": "2015-02-08",
        },
        {
            "id": 9999961,
            "name": "Similar Series Order High Internal",
            "first_air_date": "2016-03-01",
        },
    ]

    with (
        patch.object(
            service._tmdb,
            "get_series_recommendations",
            new_callable=AsyncMock,
            return_value=rec_items,
        ),
        patch.object(service._tmdb, "get_series_detail", new_callable=AsyncMock) as mock_detail,
    ):
        result = await service.get_similar_series(db, "similar-series-test-source-order-2008")

    mock_detail.assert_not_called()
    slugs = [r.slug for r in result.results]
    assert slugs == [
        "similar-series-order-high-internal-2016",
        "similar-series-order-low-internal-2015",
    ]


async def test_get_similar_series_limits_to_10(db):
    """Only up to 10 results are returned even if TMDB returns more."""
    series = await repo.upsert_series(
        db, _make_source_series_dict("similar-series-test-source-limit-2008")
    )
    await upsert_external_id(db, "SERIES", series.id, "TMDB", _SOURCE_TMDB_ID_LIMIT)

    # 15 recommendation items from TMDB — all with unique IDs and names
    rec_items = [
        {"id": 9999820 + i, "name": f"Limit Test Series {i}", "first_air_date": "2020-01-01"}
        for i in range(15)
    ]

    def make_detail(tmdb_id: int) -> dict:
        idx = tmdb_id - 9999820
        return {
            "id": tmdb_id,
            "name": f"Limit Test Series {idx}",
            "original_name": f"Limit Test Series {idx}",
            "overview": "",
            "first_air_date": "2020-01-01",
            "last_air_date": None,
            "number_of_seasons": 1,
            "number_of_episodes": 10,
            "status": "Ended",
            "original_language": "en",
            "poster_path": None,
            "backdrop_path": None,
            "vote_average": 7.0,
            "vote_count": 500,
            "genres": [],
            "created_by": [],
        }

    async def fake_get_series_detail(tid: int) -> dict:
        return make_detail(tid)

    with (
        patch.object(
            service._tmdb,
            "get_series_recommendations",
            new_callable=AsyncMock,
            return_value=rec_items,
        ),
        patch.object(
            service._tmdb,
            "get_series_detail",
            side_effect=fake_get_series_detail,
        ),
    ):
        result = await service.get_similar_series(db, "similar-series-test-source-limit-2008")

    assert len(result.results) == 10
