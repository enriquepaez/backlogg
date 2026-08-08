"""Repository tests for backlogg/lists/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers list CRUD, global slug uniqueness helper, item append/idempotency,
position re-packing on removal, reorder and the cross-type resolution.
"""

from datetime import UTC, datetime

from backlogg.books.repository import upsert_book
from backlogg.games.repository import upsert_game
from backlogg.lists.repository import (
    add_list_item,
    count_list_items,
    create_list,
    delete_list,
    get_list_by_slug,
    get_list_item,
    get_list_items,
    list_user_lists,
    remove_list_item,
    reorder_list_items,
    resolve_list_items,
    slug_exists,
    update_list,
)
from backlogg.movies.repository import upsert_movie
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Repo List Movie") -> dict:
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


def _series_data(slug: str, title: str = "Repo List Series") -> dict:
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


def _book_data(slug: str, title: str = "Repo List Book") -> dict:
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


def _game_data(slug: str, title: str = "Repo List Game") -> dict:
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


# ── list CRUD ───────────────────────────────────────────────────────────────


async def test_create_and_get_list(db):
    user_id = await _make_user(db, "lists-repo-user-1")
    created = await create_list(
        db, user_id=user_id, slug="repo-list-1", title="My List", description="d", is_public=True
    )
    assert created.id is not None

    fetched = await get_list_by_slug(db, "repo-list-1")
    assert fetched is not None
    assert fetched.title == "My List"
    assert fetched.is_public is True


async def test_slug_exists_global(db):
    user_id = await _make_user(db, "lists-repo-user-2")
    assert await slug_exists(db, "repo-list-2") is False
    await create_list(
        db, user_id=user_id, slug="repo-list-2", title="X", description=None, is_public=True
    )
    assert await slug_exists(db, "repo-list-2") is True


async def test_update_list_keeps_slug(db):
    user_id = await _make_user(db, "lists-repo-user-3")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-3", title="Old", description=None, is_public=True
    )
    updated = await update_list(db, user_list, {"title": "New", "is_public": False})
    assert updated.title == "New"
    assert updated.is_public is False
    assert updated.slug == "repo-list-3"


async def test_delete_list(db):
    user_id = await _make_user(db, "lists-repo-user-4")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-4", title="Del", description=None, is_public=True
    )
    await delete_list(db, user_list)
    assert await get_list_by_slug(db, "repo-list-4") is None


# ── list items ──────────────────────────────────────────────────────────────


async def test_add_item_appends_and_is_idempotent(db):
    user_id = await _make_user(db, "lists-repo-user-5")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-5", title="L", description=None, is_public=True
    )
    m1 = await upsert_movie(db, _movie_data("repo-list-movie-1"))
    m2 = await upsert_movie(db, _movie_data("repo-list-movie-2"))

    first = await add_list_item(db, user_list.id, "MOVIE", m1.id)
    second = await add_list_item(db, user_list.id, "MOVIE", m2.id)
    assert first.position == 0
    assert second.position == 1

    # Idempotent: adding the same item again does not duplicate or move it.
    again = await add_list_item(db, user_list.id, "MOVIE", m1.id)
    assert again.id == first.id
    assert again.position == 0
    assert await count_list_items(db, user_list.id) == 2


async def test_remove_item_repacks_positions(db):
    user_id = await _make_user(db, "lists-repo-user-6")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-6", title="L", description=None, is_public=True
    )
    m1 = await upsert_movie(db, _movie_data("repo-list-movie-3"))
    m2 = await upsert_movie(db, _movie_data("repo-list-movie-4"))
    m3 = await upsert_movie(db, _movie_data("repo-list-movie-5"))
    await add_list_item(db, user_list.id, "MOVIE", m1.id)
    await add_list_item(db, user_list.id, "MOVIE", m2.id)
    await add_list_item(db, user_list.id, "MOVIE", m3.id)

    removed = await remove_list_item(db, user_list.id, "MOVIE", m2.id)
    assert removed is True

    items = await get_list_items(db, user_list.id)
    assert [i.position for i in items] == [0, 1]
    assert [i.item_id for i in items] == [m1.id, m3.id]

    # Idempotent no-op removal.
    assert await remove_list_item(db, user_list.id, "MOVIE", m2.id) is False


async def test_reorder_items(db):
    user_id = await _make_user(db, "lists-repo-user-7")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-7", title="L", description=None, is_public=True
    )
    m1 = await upsert_movie(db, _movie_data("repo-list-movie-6"))
    s1 = await upsert_series(db, _series_data("repo-list-series-1"))
    await add_list_item(db, user_list.id, "MOVIE", m1.id)
    await add_list_item(db, user_list.id, "SERIES", s1.id)

    await reorder_list_items(db, user_list.id, [("SERIES", s1.id), ("MOVIE", m1.id)])

    items = await get_list_items(db, user_list.id)
    ordered = sorted(items, key=lambda i: i.position)
    assert [(i.item_type, i.item_id) for i in ordered] == [("SERIES", s1.id), ("MOVIE", m1.id)]


async def test_resolve_list_items_cross_type_in_order(db):
    user_id = await _make_user(db, "lists-repo-user-8")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-8", title="L", description=None, is_public=True
    )
    movie = await upsert_movie(db, _movie_data("repo-list-movie-7"))
    series = await upsert_series(db, _series_data("repo-list-series-2"))
    book = await upsert_book(db, _book_data("repo-list-book-1"))
    game = await upsert_game(db, _game_data("repo-list-game-1"))

    await add_list_item(db, user_list.id, "GAME", game.id)
    await add_list_item(db, user_list.id, "BOOK", book.id)
    await add_list_item(db, user_list.id, "SERIES", series.id)
    await add_list_item(db, user_list.id, "MOVIE", movie.id)

    rows = await resolve_list_items(db, user_list.id)
    assert [r.item_type for r in rows] == ["GAME", "BOOK", "SERIES", "MOVIE"]
    assert [r.position for r in rows] == [0, 1, 2, 3]


async def test_list_user_lists_visibility(db):
    user_id = await _make_user(db, "lists-repo-user-9")
    await create_list(
        db, user_id=user_id, slug="repo-list-9-pub", title="Pub", description=None, is_public=True
    )
    await create_list(
        db,
        user_id=user_id,
        slug="repo-list-9-priv",
        title="Priv",
        description=None,
        is_public=False,
    )

    public_only = await list_user_lists(db, user_id, include_private=False)
    assert {ul.slug for ul, _ in public_only} == {"repo-list-9-pub"}

    all_lists = await list_user_lists(db, user_id, include_private=True)
    assert {ul.slug for ul, _ in all_lists} == {"repo-list-9-pub", "repo-list-9-priv"}


async def test_list_user_lists_item_count(db):
    user_id = await _make_user(db, "lists-repo-user-10")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-10", title="L", description=None, is_public=True
    )
    m1 = await upsert_movie(db, _movie_data("repo-list-movie-8"))
    await add_list_item(db, user_list.id, "MOVIE", m1.id)

    rows = await list_user_lists(db, user_id, include_private=True)
    counts = {ul.slug: c for ul, c in rows}
    assert counts["repo-list-10"] == 1


async def test_get_list_item_lookup(db):
    user_id = await _make_user(db, "lists-repo-user-11")
    user_list = await create_list(
        db, user_id=user_id, slug="repo-list-11", title="L", description=None, is_public=True
    )
    m1 = await upsert_movie(db, _movie_data("repo-list-movie-9"))
    assert await get_list_item(db, user_list.id, "MOVIE", m1.id) is None
    await add_list_item(db, user_list.id, "MOVIE", m1.id)
    assert await get_list_item(db, user_list.id, "MOVIE", m1.id) is not None
