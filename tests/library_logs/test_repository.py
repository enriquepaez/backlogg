"""Repository tests for backlogg/library_logs/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers plain-insert create (multiple logs for the same item, unlike the
upsert semantics of ratings/library), delete, the per-item listing and the
cross-type UNION ALL user listing.
"""

from datetime import UTC, date, datetime

from backlogg.books.repository import upsert_book
from backlogg.games.repository import upsert_game
from backlogg.library_logs.repository import (
    create_log,
    delete_log,
    get_log_by_id,
    list_logs_for_item,
    list_user_log,
)
from backlogg.movies.repository import upsert_movie
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Repo Log Movie") -> dict:
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


def _series_data(slug: str, title: str = "Repo Log Series") -> dict:
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


def _book_data(slug: str, title: str = "Repo Log Book") -> dict:
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


def _game_data(slug: str, title: str = "Repo Log Game") -> dict:
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


# ── create / get / delete ────────────────────────────────────────────────


async def test_create_log_creates(db):
    movie = await upsert_movie(db, _movie_data("repo-log-movie-1"))
    user_id = await _make_user(db, "log-repo-user-1")

    log = await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note=None,
    )

    assert log.id is not None
    assert log.logged_on == date(2024, 1, 1)
    assert log.rewatch is False
    assert log.note is None
    assert log.created_at is not None


async def test_create_log_allows_multiple_for_same_item(db):
    """No unique constraint on (user, item) — a second log for the same item
    is a distinct row, unlike ratings/library which upsert."""
    movie = await upsert_movie(db, _movie_data("repo-log-movie-2"))
    user_id = await _make_user(db, "log-repo-user-2")

    first = await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note="First watch",
    )
    second = await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 6, 15),
        rewatch=True,
        note="Rewatch",
    )

    assert first.id != second.id

    rows, total = await list_logs_for_item(db, "MOVIE", movie.id, page=1, limit=20)
    assert total == 2
    assert {row.id for row in rows} == {first.id, second.id}


async def test_get_log_by_id_not_found(db):
    assert await get_log_by_id(db, 999_999) is None


async def test_delete_log(db):
    movie = await upsert_movie(db, _movie_data("repo-log-movie-3"))
    user_id = await _make_user(db, "log-repo-user-3")

    log = await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note=None,
    )
    await delete_log(db, log)

    assert await get_log_by_id(db, log.id) is None


# ── list_logs_for_item ───────────────────────────────────────────────────


async def test_list_logs_for_item_orders_newest_logged_on_first(db):
    movie = await upsert_movie(db, _movie_data("repo-log-movie-4"))
    user_id = await _make_user(db, "log-repo-user-4")

    await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note=None,
    )
    await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 12, 31),
        rewatch=True,
        note=None,
    )

    rows, total = await list_logs_for_item(db, "MOVIE", movie.id, page=1, limit=20)
    assert total == 2
    assert rows[0].logged_on == date(2024, 12, 31)
    assert rows[1].logged_on == date(2024, 1, 1)


async def test_list_logs_for_item_empty(db):
    movie = await upsert_movie(db, _movie_data("repo-log-movie-5"))
    rows, total = await list_logs_for_item(db, "MOVIE", movie.id, page=1, limit=20)
    assert rows == []
    assert total == 0


# ── list_user_log (cross-type UNION ALL) ─────────────────────────────────


async def test_list_user_log_cross_type_union(db):
    user_id = await _make_user(db, "log-repo-user-5")
    movie = await upsert_movie(db, _movie_data("repo-log-movie-6"))
    series = await upsert_series(db, _series_data("repo-log-series-1"))
    book = await upsert_book(db, _book_data("repo-log-book-1"))
    game = await upsert_game(db, _game_data("repo-log-game-1"))

    await create_log(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note=None,
    )
    await create_log(
        db,
        user_id=user_id,
        item_type="SERIES",
        item_id=series.id,
        logged_on=date(2024, 2, 1),
        rewatch=False,
        note=None,
    )
    await create_log(
        db,
        user_id=user_id,
        item_type="BOOK",
        item_id=book.id,
        logged_on=date(2024, 3, 1),
        rewatch=False,
        note=None,
    )
    await create_log(
        db,
        user_id=user_id,
        item_type="GAME",
        item_id=game.id,
        logged_on=date(2024, 4, 1),
        rewatch=False,
        note=None,
    )

    rows, total = await list_user_log(db, user_id=user_id, page=1, limit=20)
    assert total == 4
    assert {row.item_type for row in rows} == {"MOVIE", "SERIES", "BOOK", "GAME"}
    # Newest logged_on first.
    assert rows[0].item_type == "GAME"


async def test_list_user_log_excludes_other_users(db):
    user_a = await _make_user(db, "log-repo-user-6")
    user_b = await _make_user(db, "log-repo-user-7")
    movie = await upsert_movie(db, _movie_data("repo-log-movie-7"))

    await create_log(
        db,
        user_id=user_a,
        item_type="MOVIE",
        item_id=movie.id,
        logged_on=date(2024, 1, 1),
        rewatch=False,
        note=None,
    )

    rows, total = await list_user_log(db, user_id=user_b, page=1, limit=20)
    assert total == 0
    assert rows == []


async def test_list_user_log_pagination(db):
    user_id = await _make_user(db, "log-repo-user-8")
    movie = await upsert_movie(db, _movie_data("repo-log-movie-8"))

    for day in range(1, 6):
        await create_log(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            logged_on=date(2024, 1, day),
            rewatch=False,
            note=None,
        )

    page1, total = await list_user_log(db, user_id=user_id, page=1, limit=2)
    assert total == 5
    assert len(page1) == 2
    assert page1[0].logged_on == date(2024, 1, 5)

    page2, _ = await list_user_log(db, user_id=user_id, page=2, limit=2)
    assert len(page2) == 2
    assert page2[0].logged_on == date(2024, 1, 3)
