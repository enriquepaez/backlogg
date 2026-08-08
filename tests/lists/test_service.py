"""Service tests for backlogg/lists/service.py.

Exercises the business-logic layer directly against the real test DB: slug
derivation + global collision suffixing, ownership (403), private visibility
(404), item add/remove idempotency, reorder validation and per-user listing.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from backlogg.lists import service
from backlogg.lists.schemas import ListCreate, ListItemRef, ListReorder, ListUpdate
from backlogg.movies.repository import upsert_movie
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Svc List Movie") -> dict:
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


def _series_data(slug: str, title: str = "Svc List Series") -> dict:
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


async def _make_user(db, username: str):
    return await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )


# ── create + slug derivation ─────────────────────────────────────────────────


async def test_create_derives_slug_from_title(db):
    user = await _make_user(db, "lists-svc-user-1")
    out = await service.create_list(db, ListCreate(title="Best Sci-Fi Ever"), user)
    assert out.slug == "best-sci-fi-ever"
    assert out.title == "Best Sci-Fi Ever"
    assert out.item_count == 0
    assert out.items == []


async def test_create_slug_collision_gets_suffix(db):
    user1 = await _make_user(db, "lists-svc-user-2")
    user2 = await _make_user(db, "lists-svc-user-3")

    a = await service.create_list(db, ListCreate(title="Collision List"), user1)
    b = await service.create_list(db, ListCreate(title="Collision List"), user2)
    c = await service.create_list(db, ListCreate(title="Collision List"), user1)

    assert a.slug == "collision-list"
    assert b.slug == "collision-list-2"
    assert c.slug == "collision-list-3"


# ── ownership + visibility ───────────────────────────────────────────────────


async def test_update_by_non_owner_is_403(db):
    owner = await _make_user(db, "lists-svc-user-4")
    other = await _make_user(db, "lists-svc-user-5")
    created = await service.create_list(db, ListCreate(title="Owner List A"), owner)

    with pytest.raises(HTTPException) as exc:
        await service.update_list(db, created.slug, ListUpdate(title="Hacked"), other)
    assert exc.value.status_code == 403


async def test_update_unknown_slug_is_404(db):
    user = await _make_user(db, "lists-svc-user-6")
    with pytest.raises(HTTPException) as exc:
        await service.update_list(db, "no-such-list-svc", ListUpdate(title="x"), user)
    assert exc.value.status_code == 404


async def test_delete_by_non_owner_is_403(db):
    owner = await _make_user(db, "lists-svc-user-7")
    other = await _make_user(db, "lists-svc-user-8")
    created = await service.create_list(db, ListCreate(title="Owner List B"), owner)

    with pytest.raises(HTTPException) as exc:
        await service.delete_list(db, created.slug, other)
    assert exc.value.status_code == 403


async def test_get_private_list_hidden_from_non_owner(db):
    owner = await _make_user(db, "lists-svc-user-9")
    other = await _make_user(db, "lists-svc-user-10")
    created = await service.create_list(db, ListCreate(title="Secret List", is_public=False), owner)

    # Owner sees it.
    got = await service.get_list(db, created.slug, owner)
    assert got.slug == created.slug

    # Anonymous and other users get a 404 (existence hidden).
    with pytest.raises(HTTPException) as exc_anon:
        await service.get_list(db, created.slug, None)
    assert exc_anon.value.status_code == 404

    with pytest.raises(HTTPException) as exc_other:
        await service.get_list(db, created.slug, other)
    assert exc_other.value.status_code == 404


async def test_get_public_list_visible_to_anonymous(db):
    owner = await _make_user(db, "lists-svc-user-11")
    created = await service.create_list(db, ListCreate(title="Open List"), owner)
    got = await service.get_list(db, created.slug, None)
    assert got.slug == created.slug


# ── items ────────────────────────────────────────────────────────────────────


async def test_add_item_idempotent_and_appends(db):
    user = await _make_user(db, "lists-svc-user-12")
    created = await service.create_list(db, ListCreate(title="Item List"), user)
    await upsert_movie(db, _movie_data("svc-list-movie-1"))
    await upsert_series(db, _series_data("svc-list-series-1"))

    out = await service.add_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-1"), user
    )
    assert [i.slug for i in out.items] == ["svc-list-movie-1"]

    out = await service.add_item(
        db, created.slug, ListItemRef(item_type="series", slug="svc-list-series-1"), user
    )
    assert [i.item_type for i in out.items] == ["MOVIE", "SERIES"]

    # Idempotent re-add: no duplicate, order preserved.
    out = await service.add_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-1"), user
    )
    assert out.item_count == 2


async def test_add_item_unknown_content_is_404(db):
    user = await _make_user(db, "lists-svc-user-13")
    created = await service.create_list(db, ListCreate(title="Missing Item List"), user)
    with pytest.raises(HTTPException) as exc:
        await service.add_item(
            db, created.slug, ListItemRef(item_type="movie", slug="ghost-movie"), user
        )
    assert exc.value.status_code == 404


async def test_remove_item_idempotent(db):
    user = await _make_user(db, "lists-svc-user-14")
    created = await service.create_list(db, ListCreate(title="Remove List"), user)
    await upsert_movie(db, _movie_data("svc-list-movie-2"))
    await service.add_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-2"), user
    )

    out = await service.remove_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-2"), user
    )
    assert out.item_count == 0

    # Removing again is a no-op success.
    out = await service.remove_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-2"), user
    )
    assert out.item_count == 0


async def test_add_item_by_non_owner_is_403(db):
    owner = await _make_user(db, "lists-svc-user-15")
    other = await _make_user(db, "lists-svc-user-16")
    created = await service.create_list(db, ListCreate(title="Owner Item List"), owner)
    await upsert_movie(db, _movie_data("svc-list-movie-3"))

    with pytest.raises(HTTPException) as exc:
        await service.add_item(
            db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-3"), other
        )
    assert exc.value.status_code == 403


# ── reorder ──────────────────────────────────────────────────────────────────


async def test_reorder_changes_order(db):
    user = await _make_user(db, "lists-svc-user-17")
    created = await service.create_list(db, ListCreate(title="Reorder List"), user)
    await upsert_movie(db, _movie_data("svc-list-movie-4"))
    await upsert_series(db, _series_data("svc-list-series-2"))
    await service.add_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-4"), user
    )
    await service.add_item(
        db, created.slug, ListItemRef(item_type="series", slug="svc-list-series-2"), user
    )

    out = await service.reorder_items(
        db,
        created.slug,
        ListReorder(
            items=[
                ListItemRef(item_type="series", slug="svc-list-series-2"),
                ListItemRef(item_type="movie", slug="svc-list-movie-4"),
            ]
        ),
        user,
    )
    assert [i.slug for i in out.items] == ["svc-list-series-2", "svc-list-movie-4"]


async def test_reorder_mismatched_set_is_422(db):
    user = await _make_user(db, "lists-svc-user-18")
    created = await service.create_list(db, ListCreate(title="Bad Reorder List"), user)
    await upsert_movie(db, _movie_data("svc-list-movie-5"))
    await upsert_series(db, _series_data("svc-list-series-3"))
    await service.add_item(
        db, created.slug, ListItemRef(item_type="movie", slug="svc-list-movie-5"), user
    )
    await service.add_item(
        db, created.slug, ListItemRef(item_type="series", slug="svc-list-series-3"), user
    )

    # Only one of the two items provided → mismatch.
    with pytest.raises(HTTPException) as exc:
        await service.reorder_items(
            db,
            created.slug,
            ListReorder(items=[ListItemRef(item_type="movie", slug="svc-list-movie-5")]),
            user,
        )
    assert exc.value.status_code == 422


# ── per-user listing ─────────────────────────────────────────────────────────


async def test_get_user_lists_hides_private_from_others(db):
    owner = await _make_user(db, "lists-svc-user-19")
    other = await _make_user(db, "lists-svc-user-20")
    await service.create_list(db, ListCreate(title="Public One"), owner)
    await service.create_list(db, ListCreate(title="Private One", is_public=False), owner)

    # Owner sees both.
    as_owner = await service.get_user_lists(db, "lists-svc-user-19", owner)
    assert as_owner.total == 2

    # Anonymous / other only see the public one.
    as_anon = await service.get_user_lists(db, "lists-svc-user-19", None)
    assert as_anon.total == 1
    assert as_anon.lists[0].is_public is True

    as_other = await service.get_user_lists(db, "lists-svc-user-19", other)
    assert as_other.total == 1


async def test_get_user_lists_unknown_user_is_404(db):
    with pytest.raises(HTTPException) as exc:
        await service.get_user_lists(db, "nobody-lists-ever", None)
    assert exc.value.status_code == 404
