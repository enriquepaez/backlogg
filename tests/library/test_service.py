"""Service tests for backlogg/library/service.py.

Exercises the business-logic layer directly (404 on unknown slug/user, upsert
semantics, viewer_status resolution, counts) against the real test DB.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from backlogg.library import service
from backlogg.library.schemas import LibraryStatus, LibraryTypeFilter
from backlogg.movies.repository import upsert_movie
from backlogg.series.repository import upsert_series
from backlogg.users.models import User
from backlogg.users.repository import create_user


def _movie_data(slug: str) -> dict:
    return {
        "title": "Svc Library Movie",
        "original_title": "Svc Library Movie",
        "slug": slug,
        "overview": "overview",
        "release_date": None,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series_data(slug: str) -> dict:
    return {
        "title": "Svc Library Series",
        "original_title": "Svc Library Series",
        "slug": slug,
        "overview": "overview",
        "first_air_date": None,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


async def _make_user(db, username: str) -> User:
    return await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )


async def test_set_library_status_creates_entry(db):
    await upsert_movie(db, _movie_data("svc-library-movie-1"))
    user = await _make_user(db, "library-svc-user-1")

    out = await service.set_library_status(
        db, "MOVIE", "svc-library-movie-1", LibraryStatus.want, user
    )
    assert out.status == "want"
    assert out.slug == "svc-library-movie-1"
    assert out.item_type == "MOVIE"


async def test_set_library_status_upserts(db):
    await upsert_movie(db, _movie_data("svc-library-movie-2"))
    user = await _make_user(db, "library-svc-user-2")

    await service.set_library_status(db, "MOVIE", "svc-library-movie-2", LibraryStatus.want, user)
    out = await service.set_library_status(
        db, "MOVIE", "svc-library-movie-2", LibraryStatus.completed, user
    )
    assert out.status == "completed"


async def test_set_library_status_unknown_slug_raises_404(db):
    user = await _make_user(db, "library-svc-user-3")
    with pytest.raises(HTTPException) as exc:
        await service.set_library_status(db, "MOVIE", "svc-library-nope", LibraryStatus.want, user)
    assert exc.value.status_code == 404


async def test_remove_library_entry_not_found_raises_404(db):
    await upsert_movie(db, _movie_data("svc-library-movie-3"))
    user = await _make_user(db, "library-svc-user-4")
    with pytest.raises(HTTPException) as exc:
        await service.remove_library_entry(db, "MOVIE", "svc-library-movie-3", user)
    assert exc.value.status_code == 404


async def test_remove_library_entry_deletes(db):
    movie = await upsert_movie(db, _movie_data("svc-library-movie-4"))
    user = await _make_user(db, "library-svc-user-5")

    await service.set_library_status(db, "MOVIE", "svc-library-movie-4", LibraryStatus.want, user)
    await service.remove_library_entry(db, "MOVIE", "svc-library-movie-4", user)

    assert await service.get_viewer_status(db, "MOVIE", movie.id, user.id) is None


async def test_get_viewer_status_anonymous_is_none(db):
    movie = await upsert_movie(db, _movie_data("svc-library-movie-5"))
    assert await service.get_viewer_status(db, "MOVIE", movie.id, None) is None


async def test_get_viewer_status_returns_status(db):
    movie = await upsert_movie(db, _movie_data("svc-library-movie-6"))
    user = await _make_user(db, "library-svc-user-6")
    await service.set_library_status(
        db, "MOVIE", "svc-library-movie-6", LibraryStatus.in_progress, user
    )
    assert await service.get_viewer_status(db, "MOVIE", movie.id, user.id) == "in_progress"


async def test_get_user_library_unknown_user_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await service.get_user_library(db, "no-such-user-library", None, None, 1, 20)
    assert exc.value.status_code == 404


async def test_get_user_library_filters(db):
    await upsert_movie(db, _movie_data("svc-library-movie-7"))
    await upsert_series(db, _series_data("svc-library-series-1"))
    user = await _make_user(db, "library-svc-user-7")

    await service.set_library_status(db, "MOVIE", "svc-library-movie-7", LibraryStatus.want, user)
    await service.set_library_status(
        db, "SERIES", "svc-library-series-1", LibraryStatus.completed, user
    )

    only_movies = await service.get_user_library(
        db, "library-svc-user-7", None, LibraryTypeFilter.movie, 1, 20
    )
    assert only_movies.total == 1
    assert only_movies.items[0].item.item_type == "MOVIE"

    only_want = await service.get_user_library(
        db, "library-svc-user-7", LibraryStatus.want, None, 1, 20
    )
    assert only_want.total == 1
    assert only_want.items[0].status == "want"


async def test_get_library_counts(db):
    await upsert_movie(db, _movie_data("svc-library-movie-8"))
    user = await _make_user(db, "library-svc-user-8")
    await service.set_library_status(db, "MOVIE", "svc-library-movie-8", LibraryStatus.want, user)

    counts = await service.get_library_counts(db, user.id)
    assert counts.want == 1
    assert counts.completed == 0
