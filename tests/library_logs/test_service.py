"""Service tests for backlogg/library_logs/service.py.

Exercises the business-logic layer directly (404 on unknown slug/user/log,
default logged_on, multiple logs per item, ownership check on delete) against
the real test DB. Also verifies library_logs does not interfere with
user_ratings (feature 28) — the two tables are fully decoupled.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from backlogg.library_logs import service
from backlogg.library_logs.schemas import LogIn
from backlogg.movies.repository import upsert_movie
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn
from backlogg.users.models import User
from backlogg.users.repository import create_user


def _movie_data(slug: str) -> dict:
    return {
        "title": "Svc Log Movie",
        "original_title": "Svc Log Movie",
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


async def test_create_log_entry_creates(db):
    await upsert_movie(db, _movie_data("svc-log-movie-1"))
    user = await _make_user(db, "log-svc-user-1")

    out = await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-1", LogIn(logged_on=date(2024, 5, 1)), user
    )
    assert out.item_type == "MOVIE"
    assert out.slug == "svc-log-movie-1"
    assert out.logged_on == date(2024, 5, 1)
    assert out.rewatch is False
    assert out.note is None


async def test_create_log_entry_defaults_logged_on_to_today(db):
    await upsert_movie(db, _movie_data("svc-log-movie-2"))
    user = await _make_user(db, "log-svc-user-2")

    out = await service.create_log_entry(db, "MOVIE", "svc-log-movie-2", LogIn(), user)
    assert out.logged_on == date.today()


async def test_create_log_entry_allows_multiple_for_same_item(db):
    await upsert_movie(db, _movie_data("svc-log-movie-3"))
    user = await _make_user(db, "log-svc-user-3")

    first = await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-3", LogIn(logged_on=date(2024, 1, 1)), user
    )
    second = await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-3", LogIn(logged_on=date(2024, 2, 1), rewatch=True), user
    )
    assert first.id != second.id

    listing = await service.list_item_log(db, "MOVIE", "svc-log-movie-3", 1, 20)
    assert listing.total == 2


async def test_create_log_entry_unknown_slug_raises_404(db):
    user = await _make_user(db, "log-svc-user-4")
    with pytest.raises(HTTPException) as exc:
        await service.create_log_entry(db, "MOVIE", "svc-log-nope", LogIn(), user)
    assert exc.value.status_code == 404


async def test_list_item_log_unknown_slug_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await service.list_item_log(db, "MOVIE", "svc-log-nope-2", 1, 20)
    assert exc.value.status_code == 404


async def test_delete_log_entry_removes(db):
    await upsert_movie(db, _movie_data("svc-log-movie-5"))
    user = await _make_user(db, "log-svc-user-5")

    created = await service.create_log_entry(db, "MOVIE", "svc-log-movie-5", LogIn(), user)
    await service.delete_log_entry(db, created.id, user)

    listing = await service.list_item_log(db, "MOVIE", "svc-log-movie-5", 1, 20)
    assert listing.total == 0


async def test_delete_log_entry_not_found_raises_404(db):
    user = await _make_user(db, "log-svc-user-6")
    with pytest.raises(HTTPException) as exc:
        await service.delete_log_entry(db, 999_999, user)
    assert exc.value.status_code == 404


async def test_delete_log_entry_owned_by_another_user_raises_404(db):
    await upsert_movie(db, _movie_data("svc-log-movie-6"))
    owner = await _make_user(db, "log-svc-user-7")
    other = await _make_user(db, "log-svc-user-8")

    created = await service.create_log_entry(db, "MOVIE", "svc-log-movie-6", LogIn(), owner)

    with pytest.raises(HTTPException) as exc:
        await service.delete_log_entry(db, created.id, other)
    assert exc.value.status_code == 404


async def test_get_user_log_unknown_user_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await service.get_user_log(db, "no-such-user-log", 1, 20)
    assert exc.value.status_code == 404


async def test_get_user_log_returns_entries(db):
    await upsert_movie(db, _movie_data("svc-log-movie-7"))
    user = await _make_user(db, "log-svc-user-9")

    await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-7", LogIn(logged_on=date(2024, 1, 1)), user
    )

    listing = await service.get_user_log(db, "log-svc-user-9", 1, 20)
    assert listing.total == 1
    assert listing.items[0].item.item_type == "MOVIE"
    assert listing.items[0].item.slug == "svc-log-movie-7"


# ── no interference with user_ratings (feature 28) ───────────────────────


async def test_library_log_does_not_affect_user_ratings(db):
    await upsert_movie(db, _movie_data("svc-log-movie-8"))
    user = await _make_user(db, "log-svc-user-10")

    # Create a log entry only — no rating.
    await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-8", LogIn(logged_on=date(2024, 1, 1)), user
    )

    ratings = await ratings_service.list_item_ratings(db, "MOVIE", "svc-log-movie-8", 1, 20)
    assert ratings.total == 0


async def test_user_rating_does_not_affect_library_log(db):
    await upsert_movie(db, _movie_data("svc-log-movie-9"))
    user = await _make_user(db, "log-svc-user-11")

    # Create a rating only — no log entry.
    await ratings_service.rate_item(
        db, "MOVIE", "svc-log-movie-9", RatingIn(score=5, review_text="Great"), user
    )

    listing = await service.list_item_log(db, "MOVIE", "svc-log-movie-9", 1, 20)
    assert listing.total == 0


async def test_log_and_rating_coexist_independently(db):
    await upsert_movie(db, _movie_data("svc-log-movie-10"))
    user = await _make_user(db, "log-svc-user-12")

    await ratings_service.rate_item(
        db, "MOVIE", "svc-log-movie-10", RatingIn(score=4, review_text=None), user
    )
    await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-10", LogIn(logged_on=date(2024, 3, 3)), user
    )
    await service.create_log_entry(
        db, "MOVIE", "svc-log-movie-10", LogIn(logged_on=date(2024, 4, 4), rewatch=True), user
    )

    ratings = await ratings_service.list_item_ratings(db, "MOVIE", "svc-log-movie-10", 1, 20)
    logs = await service.list_item_log(db, "MOVIE", "svc-log-movie-10", 1, 20)
    assert ratings.total == 1
    assert logs.total == 2
