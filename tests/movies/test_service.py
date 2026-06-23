from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.movies import repository as repo
from backlogg.movies import service


def _make_tmdb_detail(tmdb_id: int = 123) -> dict:
    return {
        "id": tmdb_id,
        "title": "Inception",
        "original_title": "Inception",
        "overview": "A mind-bending thriller.",
        "release_date": "2010-07-16",
        "runtime": 148,
        "original_language": "en",
        "poster_path": "/inception.jpg",
        "backdrop_path": "/inception_backdrop.jpg",
        "budget": 160000000,
        "revenue": 836000000,
        "status": "Released",
        "vote_average": 8.8,
        "vote_count": 30000,
        "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
    }


def _make_movie_dict() -> dict:
    return {
        "title": "Inception",
        "original_title": "Inception",
        "slug": "inception-2010",
        "overview": "A mind-bending thriller.",
        "release_date": date(2010, 7, 16),
        "runtime": 148,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/inception.jpg",
        "backdrop_url": "https://image.tmdb.org/t/p/w500/inception_backdrop.jpg",
        "budget": 160000000,
        "revenue": 836000000,
        "status": "Released",
        "rating_external": 8.8,
        "rating_count_external": 30000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Action", "slug": "action"},
            {"name": "Science Fiction", "slug": "science-fiction"},
        ],
    }


async def test_get_movie_found_in_db(db):
    """When movie exists in DB, service returns it without calling TMDB."""
    # Pre-insert the movie
    await repo.upsert_movie(db, _make_movie_dict())

    with patch.object(service._tmdb, "search_movie", new_callable=AsyncMock) as mock_search:
        result = await service.get_movie(db, "inception-2010")

    assert result.slug == "inception-2010"
    mock_search.assert_not_called()


async def test_get_movie_fallback_to_tmdb(db):
    """When movie is not in DB, service calls TMDB, persists and returns it."""
    search_result = {"id": 27205}
    detail = _make_tmdb_detail(tmdb_id=27205)

    with (
        patch.object(
            service._tmdb, "search_movie", new_callable=AsyncMock, return_value=search_result
        ),
        patch.object(
            service._tmdb, "get_movie_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ),
    ):
        result = await service.get_movie(db, "inception-2010")

    assert result.slug == "inception-2010"
    assert result.title == "Inception"

    # Verify persisted in DB
    persisted = await repo.get_movie_by_slug(db, "inception-2010")
    assert persisted is not None


async def test_get_movie_not_found_anywhere(db):
    """When TMDB returns None, service raises HTTP 404."""
    with (
        patch.object(service._tmdb, "search_movie", new_callable=AsyncMock, return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_movie(db, "this-slug-does-not-exist-9999")

    assert exc_info.value.status_code == 404


async def test_get_movie_fallback_passes_year_from_slug(db):
    """When slug contains a year suffix, search_movie is called with that year."""
    search_result = {"id": 78}
    detail = _make_tmdb_detail(tmdb_id=78)

    with (
        patch.object(
            service._tmdb, "search_movie", new_callable=AsyncMock, return_value=search_result
        ) as mock_search,
        patch.object(
            service._tmdb, "get_movie_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ),
    ):
        await service.get_movie(db, "blade-runner-1982")

    mock_search.assert_called_once_with("blade runner", year=1982)
