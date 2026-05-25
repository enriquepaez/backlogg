from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.series import repository as repo
from backlogg.series import service


def _make_tmdb_detail(tmdb_id: int = 456) -> dict:
    return {
        "id": tmdb_id,
        "name": "Breaking Bad",
        "original_name": "Breaking Bad",
        "overview": "A chemistry teacher turned drug kingpin.",
        "first_air_date": "2008-01-20",
        "last_air_date": "2013-09-29",
        "number_of_seasons": 5,
        "number_of_episodes": 62,
        "original_language": "en",
        "poster_path": "/breakingbad.jpg",
        "backdrop_path": "/breakingbad_backdrop.jpg",
        "status": "Ended",
        "vote_average": 9.5,
        "vote_count": 12000,
        "genres": [{"id": 18, "name": "Drama"}, {"id": 80, "name": "Crime"}],
    }


def _make_series_dict() -> dict:
    return {
        "title": "Breaking Bad",
        "original_title": "Breaking Bad",
        "slug": "breaking-bad-2008",
        "overview": "A chemistry teacher turned drug kingpin.",
        "first_air_date": date(2008, 1, 20),
        "last_air_date": date(2013, 9, 29),
        "number_of_seasons": 5,
        "number_of_episodes": 62,
        "status": "Ended",
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/breakingbad.jpg",
        "backdrop_url": "https://image.tmdb.org/t/p/w500/breakingbad_backdrop.jpg",
        "rating_external": 9.5,
        "rating_count_external": 12000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Drama", "slug": "drama"},
            {"name": "Crime", "slug": "crime"},
        ],
    }


async def test_get_series_found_in_db(db):
    """When series exists in DB, service returns it without calling TMDB."""
    # Pre-insert the series
    await repo.upsert_series(db, _make_series_dict())

    with patch.object(service._tmdb, "search_series", new_callable=AsyncMock) as mock_search:
        result = await service.get_series(db, "breaking-bad-2008")

    assert result.slug == "breaking-bad-2008"
    mock_search.assert_not_called()


async def test_get_series_fallback_to_tmdb(db):
    """When series is not in DB, service calls TMDB, persists and returns it."""
    search_result = {"id": 1396}
    detail = _make_tmdb_detail(tmdb_id=1396)

    with (
        patch.object(
            service._tmdb, "search_series", new_callable=AsyncMock, return_value=search_result
        ),
        patch.object(
            service._tmdb, "get_series_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            service._tmdb,
            "get_series_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ),
    ):
        result = await service.get_series(db, "breaking-bad-2008")

    assert result.slug == "breaking-bad-2008"
    assert result.title == "Breaking Bad"

    # Verify persisted in DB
    persisted = await repo.get_series_by_slug(db, "breaking-bad-2008")
    assert persisted is not None


async def test_get_series_not_found_anywhere(db):
    """When TMDB returns None, service raises HTTP 404."""
    with (
        patch.object(service._tmdb, "search_series", new_callable=AsyncMock, return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_series(db, "this-slug-does-not-exist-9999")

    assert exc_info.value.status_code == 404
