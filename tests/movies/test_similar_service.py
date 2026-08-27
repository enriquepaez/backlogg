"""Tests for get_similar_movies service function."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.movies import repository as repo
from backlogg.movies import service
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import upsert_external_id

# Fake TMDB IDs that do NOT correspond to real movies
# Use very high numbers to avoid clashing with the real DB
_SOURCE_TMDB_ID_SIM = "9999901"
_SOURCE_TMDB_ID_LOCAL = "9999902"
_SOURCE_TMDB_ID_LIMIT = "9999903"
_SOURCE_TMDB_ID_CREDITS = "9999904"
_REC_TMDB_ID = 9999910


def _make_source_movie_dict(slug: str) -> dict:
    return {
        "title": "Fake Source Movie",
        "original_title": "Fake Source Movie",
        "slug": slug,
        "overview": "A test movie.",
        "release_date": date(2010, 7, 16),
        "runtime": 90,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": 8.0,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _make_tmdb_detail(tmdb_id: int = _REC_TMDB_ID) -> dict:
    return {
        "id": tmdb_id,
        "title": "Recommended Movie",
        "original_title": "Recommended Movie",
        "overview": "A recommended film.",
        "release_date": "2008-07-18",
        "runtime": 152,
        "original_language": "en",
        "poster_path": "/rec.jpg",
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 9.0,
        "vote_count": 28000,
        "genres": [{"id": 28, "name": "Action"}],
    }


def _make_recommendation_item(tmdb_id: int = _REC_TMDB_ID) -> dict:
    """Minimal item as returned by the TMDB recommendations list endpoint."""
    return {
        "id": tmdb_id,
        "title": "Recommended Movie",
        "release_date": "2008-07-18",
        "poster_path": "/rec.jpg",
        "vote_average": 9.0,
        "vote_count": 28000,
    }


async def test_get_similar_movies_404_for_unknown_slug(db):
    """Returns 404 when the source movie does not exist in DB."""
    with pytest.raises(HTTPException) as exc_info:
        await service.get_similar_movies(db, "slug-that-does-not-exist-similar-test-xyz")
    assert exc_info.value.status_code == 404


async def test_get_similar_movies_empty_when_no_tmdb_id(db):
    """Returns empty results when movie has no TMDB external ID."""
    await repo.upsert_movie(db, _make_source_movie_dict("similar-test-no-tmdb-id-2010"))
    # No external ID inserted — simulates a locally-only entry

    result = await service.get_similar_movies(db, "similar-test-no-tmdb-id-2010")

    assert result.results == []


async def test_get_similar_movies_persists_and_returns(db):
    """Recommendations not in DB are fetched, persisted, and returned."""
    movie = await repo.upsert_movie(db, _make_source_movie_dict("similar-test-source-sim-2010"))
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", _SOURCE_TMDB_ID_SIM)

    rec_item = _make_recommendation_item(tmdb_id=_REC_TMDB_ID)
    rec_detail = _make_tmdb_detail(tmdb_id=_REC_TMDB_ID)

    with (
        patch.object(
            service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(
            service._tmdb,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=rec_detail,
        ),
        patch.object(
            service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await service.get_similar_movies(db, "similar-test-source-sim-2010")

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Recommended Movie"
    assert item.slug == "recommended-movie-2008"
    assert item.poster_url is not None
    assert item.release_date == date(2008, 7, 18)
    assert item.rating_external == 9.0
    # Feature 69: a freshly-persisted TMDB item has no community rating yet.
    assert item.rating_internal is None

    # Verify it was persisted
    persisted = await repo.get_movie_by_slug(db, "recommended-movie-2008")
    assert persisted is not None


async def test_get_similar_movies_uses_local_if_already_present(db):
    """Items already in DB are used without calling get_movie_detail."""
    movie = await repo.upsert_movie(db, _make_source_movie_dict("similar-test-source-local-2010"))
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", _SOURCE_TMDB_ID_LOCAL)

    # Pre-seed the recommended movie in DB
    rec_dict = {
        "title": "Recommended Movie",
        "original_title": "Recommended Movie",
        "slug": "recommended-movie-local-2008",
        "overview": "A recommended film already in DB.",
        "release_date": date(2008, 7, 18),
        "runtime": 152,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/rec.jpg",
        "backdrop_url": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "rating_external": 9.0,
        "rating_count_external": 28000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }
    await repo.upsert_movie(db, rec_dict)

    # The recommendation item slug must match the pre-seeded slug.
    # recommendation item title + date -> "recommended-movie-local-2008"
    rec_item = {
        "id": _REC_TMDB_ID + 1,
        "title": "Recommended Movie Local",
        "release_date": "2008-07-18",
    }

    with (
        patch.object(
            service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(service._tmdb, "get_movie_detail", new_callable=AsyncMock) as mock_detail,
    ):
        result = await service.get_similar_movies(db, "similar-test-source-local-2010")

    # get_movie_detail should NOT have been called since item already exists
    mock_detail.assert_not_called()
    assert len(result.results) == 1
    assert result.results[0].slug == "recommended-movie-local-2008"


async def test_get_similar_movies_includes_rating_internal_from_local_movie(db):
    """Feature 69: a pre-seeded local rec movie's rating_internal travels in
    the response (not just rating_external)."""
    movie = await repo.upsert_movie(
        db, _make_source_movie_dict("similar-test-source-rating-internal-2010")
    )
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9999905")

    rec_dict = {
        "title": "Recommended Movie With Internal Rating",
        "original_title": "Recommended Movie With Internal Rating",
        "slug": "recommended-movie-with-internal-rating-2008",
        "overview": "A recommended film already in DB with a community rating.",
        "release_date": date(2008, 7, 18),
        "runtime": 152,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/rec.jpg",
        "backdrop_url": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "rating_external": 9.0,
        "rating_count_external": 28000,
        "rating_internal": 4.4,
        "rating_count_internal": 12,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }
    await repo.upsert_movie(db, rec_dict)

    rec_item = {
        "id": _REC_TMDB_ID + 2,
        "title": "Recommended Movie With Internal Rating",
        "release_date": "2008-07-18",
    }

    with (
        patch.object(
            service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(service._tmdb, "get_movie_detail", new_callable=AsyncMock),
    ):
        result = await service.get_similar_movies(db, "similar-test-source-rating-internal-2010")

    assert len(result.results) == 1
    assert result.results[0].slug == "recommended-movie-with-internal-rating-2008"
    assert result.results[0].rating_internal == 4.4


async def test_get_similar_movies_limits_to_10(db):
    """Only up to 10 results are returned even if TMDB returns more."""
    movie = await repo.upsert_movie(db, _make_source_movie_dict("similar-test-source-limit-2010"))
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", _SOURCE_TMDB_ID_LIMIT)

    # 15 recommendation items from TMDB — all with unique IDs and titles
    rec_items = [
        {"id": 9999920 + i, "title": f"Limit Test Movie {i}", "release_date": "2020-01-01"}
        for i in range(15)
    ]

    def make_detail(tmdb_id: int) -> dict:
        idx = tmdb_id - 9999920
        return {
            "id": tmdb_id,
            "title": f"Limit Test Movie {idx}",
            "original_title": f"Limit Test Movie {idx}",
            "overview": "",
            "release_date": "2020-01-01",
            "runtime": 90,
            "original_language": "en",
            "poster_path": None,
            "backdrop_path": None,
            "budget": 0,
            "revenue": 0,
            "status": "Released",
            "vote_average": 7.0,
            "vote_count": 1000,
            "genres": [],
        }

    async def fake_get_movie_detail(tid: int) -> dict:
        return make_detail(tid)

    with (
        patch.object(
            service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=rec_items,
        ),
        patch.object(
            service._tmdb,
            "get_movie_detail",
            side_effect=fake_get_movie_detail,
        ),
        patch.object(
            service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await service.get_similar_movies(db, "similar-test-source-limit-2010")

    assert len(result.results) == 10


# ── Feature 70: catalog_credits_ingestion_parity ────────────────────────────


async def test_get_similar_movies_persists_credits_for_new_movie(db):
    """A movie ingested via the similar/recommendations path gets its cast
    and crew persisted too, not just the item row (feature 70 — previously
    only the on-demand GET and the nightly job triggered credit persistence,
    leaving recommended movies without credits forever)."""
    movie = await repo.upsert_movie(db, _make_source_movie_dict("similar-test-source-credits-2010"))
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", _SOURCE_TMDB_ID_CREDITS)

    rec_item = _make_recommendation_item(tmdb_id=_REC_TMDB_ID + 3)
    rec_detail = _make_tmdb_detail(tmdb_id=_REC_TMDB_ID + 3)
    credits_data = {
        "cast": [
            {
                "id": 555001,
                "name": "Credits Test Actor",
                "character": "The Lead",
                "order": 0,
                "profile_path": None,
            }
        ],
        "crew": [
            {
                "id": 555002,
                "name": "Credits Test Director",
                "job": "Director",
                "profile_path": None,
            }
        ],
    }

    with (
        patch.object(
            service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ),
        patch.object(
            service._tmdb,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=rec_detail,
        ),
        patch.object(
            service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=credits_data,
        ),
    ):
        await service.get_similar_movies(db, "similar-test-source-credits-2010")

    rec_movie = await repo.get_movie_by_slug(db, "recommended-movie-2008")
    assert rec_movie is not None
    persisted_credits = await get_credits_for_item(db, "MOVIE", rec_movie.id)
    roles = {c.role for c in persisted_credits}
    assert "ACTOR" in roles
    assert "DIRECTOR" in roles
