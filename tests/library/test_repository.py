"""Repository tests for backlogg/library/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers upsert (create + idempotent update), status/type filtering, the
cross-type UNION ALL listing, per-status counts and viewer status lookup.
"""

from datetime import UTC, datetime

from backlogg.books.repository import upsert_book
from backlogg.games.repository import upsert_game
from backlogg.library.repository import (
    count_by_status,
    delete_library_entry,
    get_library_entry,
    get_library_status,
    list_user_library,
    upsert_library_entry,
)
from backlogg.movies.repository import upsert_movie
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Repo Library Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
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


def _series_data(slug: str, title: str = "Repo Library Series") -> dict:
    return {
        "title": title,
        "original_title": title,
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


def _book_data(slug: str, title: str = "Repo Library Book") -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_data(slug: str, title: str = "Repo Library Game") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": None,
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


async def _make_user(db, username: str) -> int:
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )
    return user.id


# ── upsert / get ──────────────────────────────────────────────────────────


async def test_upsert_library_entry_creates(db):
    movie = await upsert_movie(db, _movie_data("repo-library-movie-1"))
    user_id = await _make_user(db, "library-repo-user-1")

    entry = await upsert_library_entry(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="want"
    )

    assert entry.id is not None
    assert entry.status == "want"


async def test_upsert_library_entry_idempotent_updates_status(db):
    movie = await upsert_movie(db, _movie_data("repo-library-movie-2"))
    user_id = await _make_user(db, "library-repo-user-2")

    first = await upsert_library_entry(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="want"
    )
    second = await upsert_library_entry(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="completed"
    )

    assert first.id == second.id
    assert second.status == "completed"

    fetched = await get_library_entry(db, user_id=user_id, item_type="MOVIE", item_id=movie.id)
    assert fetched is not None
    assert fetched.status == "completed"


async def test_get_library_entry_not_found(db):
    result = await get_library_entry(db, user_id=999_999, item_type="MOVIE", item_id=999_999)
    assert result is None


async def test_get_library_status_returns_scalar(db):
    movie = await upsert_movie(db, _movie_data("repo-library-movie-3"))
    user_id = await _make_user(db, "library-repo-user-3")

    assert await get_library_status(db, user_id, "MOVIE", movie.id) is None

    await upsert_library_entry(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="in_progress"
    )
    assert await get_library_status(db, user_id, "MOVIE", movie.id) == "in_progress"


async def test_delete_library_entry(db):
    movie = await upsert_movie(db, _movie_data("repo-library-movie-4"))
    user_id = await _make_user(db, "library-repo-user-4")

    entry = await upsert_library_entry(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="want"
    )
    await delete_library_entry(db, entry)

    assert await get_library_entry(db, user_id=user_id, item_type="MOVIE", item_id=movie.id) is None


# ── list_user_library (cross-type UNION ALL + filters) ────────────────────


async def test_list_user_library_cross_type_union(db):
    user_id = await _make_user(db, "library-repo-user-5")
    movie = await upsert_movie(db, _movie_data("repo-library-movie-5"))
    series = await upsert_series(db, _series_data("repo-library-series-1"))
    book = await upsert_book(db, _book_data("repo-library-book-1"))
    game = await upsert_game(db, _game_data("repo-library-game-1"))

    await upsert_library_entry(db, user_id, "MOVIE", movie.id, "want")
    await upsert_library_entry(db, user_id, "SERIES", series.id, "completed")
    await upsert_library_entry(db, user_id, "BOOK", book.id, "want")
    await upsert_library_entry(db, user_id, "GAME", game.id, "dropped")

    rows, total = await list_user_library(
        db, user_id=user_id, status=None, item_type_filter=None, page=1, limit=20
    )
    assert total == 4
    assert {row.item_type for row in rows} == {"MOVIE", "SERIES", "BOOK", "GAME"}


async def test_list_user_library_filter_by_status(db):
    user_id = await _make_user(db, "library-repo-user-6")
    movie = await upsert_movie(db, _movie_data("repo-library-movie-6"))
    series = await upsert_series(db, _series_data("repo-library-series-2"))

    await upsert_library_entry(db, user_id, "MOVIE", movie.id, "want")
    await upsert_library_entry(db, user_id, "SERIES", series.id, "completed")

    rows, total = await list_user_library(
        db, user_id=user_id, status="want", item_type_filter=None, page=1, limit=20
    )
    assert total == 1
    assert rows[0].item_type == "MOVIE"
    assert rows[0].status == "want"


async def test_list_user_library_filter_by_type(db):
    user_id = await _make_user(db, "library-repo-user-7")
    movie = await upsert_movie(db, _movie_data("repo-library-movie-7"))
    book = await upsert_book(db, _book_data("repo-library-book-2"))

    await upsert_library_entry(db, user_id, "MOVIE", movie.id, "want")
    await upsert_library_entry(db, user_id, "BOOK", book.id, "want")

    rows, total = await list_user_library(
        db, user_id=user_id, status=None, item_type_filter="BOOK", page=1, limit=20
    )
    assert total == 1
    assert rows[0].item_type == "BOOK"


async def test_list_user_library_release_date_per_type(db):
    """Books expose first_publish_date and series first_air_date as release_date."""
    from datetime import date

    user_id = await _make_user(db, "library-repo-user-8")
    series_data = _series_data("repo-library-series-3")
    series_data["first_air_date"] = date(2001, 5, 4)
    book_data = _book_data("repo-library-book-3")
    book_data["first_publish_date"] = date(1998, 3, 2)
    series = await upsert_series(db, series_data)
    book = await upsert_book(db, book_data)

    await upsert_library_entry(db, user_id, "SERIES", series.id, "want")
    await upsert_library_entry(db, user_id, "BOOK", book.id, "want")

    rows, _ = await list_user_library(
        db, user_id=user_id, status=None, item_type_filter=None, page=1, limit=20
    )
    by_type = {row.item_type: row for row in rows}
    assert by_type["SERIES"].release_date == date(2001, 5, 4)
    assert by_type["BOOK"].release_date == date(1998, 3, 2)


async def test_list_user_library_excludes_other_users(db):
    user_a = await _make_user(db, "library-repo-user-9")
    user_b = await _make_user(db, "library-repo-user-10")
    movie = await upsert_movie(db, _movie_data("repo-library-movie-8"))

    await upsert_library_entry(db, user_a, "MOVIE", movie.id, "want")

    rows, total = await list_user_library(
        db, user_id=user_b, status=None, item_type_filter=None, page=1, limit=20
    )
    assert total == 0
    assert rows == []


# ── count_by_status ───────────────────────────────────────────────────────


async def test_count_by_status_zero_filled(db):
    user_id = await _make_user(db, "library-repo-user-11")
    counts = await count_by_status(db, user_id)
    assert counts == {"want": 0, "in_progress": 0, "completed": 0, "dropped": 0}


async def test_count_by_status_groups(db):
    user_id = await _make_user(db, "library-repo-user-12")
    movie = await upsert_movie(db, _movie_data("repo-library-movie-9"))
    series = await upsert_series(db, _series_data("repo-library-series-4"))
    book = await upsert_book(db, _book_data("repo-library-book-4"))

    await upsert_library_entry(db, user_id, "MOVIE", movie.id, "want")
    await upsert_library_entry(db, user_id, "SERIES", series.id, "want")
    await upsert_library_entry(db, user_id, "BOOK", book.id, "completed")

    counts = await count_by_status(db, user_id)
    assert counts == {"want": 2, "in_progress": 0, "completed": 1, "dropped": 0}
