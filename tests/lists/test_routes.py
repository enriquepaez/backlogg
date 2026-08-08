"""Endpoint tests for the user lists feature.

Covers:
- POST /lists (201, slug derivation, 401 without token).
- PATCH/DELETE /lists/{slug} (owner-only 403, 404).
- POST/DELETE /lists/{slug}/items (idempotency, 404 unknown item).
- PUT /lists/{slug}/items/order (reorder + 422 on mismatch).
- GET /lists/{slug} (public vs private visibility 404).
- GET /users/{username}/lists (public vs owner view).
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_data(slug: str, title: str = "Route List Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": date(2020, 1, 1),
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


def _series_data(slug: str, title: str = "Route List Series") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "first_air_date": date(2020, 1, 1),
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


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_login(client: AsyncClient, username: str) -> str:
    await client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )
    login = await client.post("/auth/login", json={"username": username, "password": "s3cret-pw"})
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── POST /lists ──────────────────────────────────────────────────────────────


async def test_create_list_without_token_returns_401(client, db):
    response = await client.post("/lists", json={"title": "No Auth List"})
    assert response.status_code == 401


async def test_create_list_returns_201_with_derived_slug(client, db):
    token = await _register_and_login(client, "route-lists-user-1")
    response = await client.post(
        "/lists", json={"title": "Best Sci-Fi", "description": "d"}, headers=_auth(token)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "best-sci-fi"
    assert body["title"] == "Best Sci-Fi"
    assert body["is_public"] is True
    assert body["items"] == []


# ── PATCH / DELETE /lists/{slug} ─────────────────────────────────────────────


async def test_patch_list_by_owner(client, db):
    token = await _register_and_login(client, "route-lists-user-2")
    created = await client.post("/lists", json={"title": "Patch Me"}, headers=_auth(token))
    slug = created.json()["slug"]

    response = await client.patch(
        f"/lists/{slug}", json={"title": "Patched", "is_public": False}, headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Patched"
    assert response.json()["is_public"] is False
    # Slug does not change on title update.
    assert response.json()["slug"] == slug


async def test_patch_list_by_non_owner_returns_403(client, db):
    owner_token = await _register_and_login(client, "route-lists-user-3")
    other_token = await _register_and_login(client, "route-lists-user-4")
    created = await client.post("/lists", json={"title": "Owned List"}, headers=_auth(owner_token))
    slug = created.json()["slug"]

    response = await client.patch(
        f"/lists/{slug}", json={"title": "Hijack"}, headers=_auth(other_token)
    )
    assert response.status_code == 403


async def test_patch_unknown_list_returns_404(client, db):
    token = await _register_and_login(client, "route-lists-user-5")
    response = await client.patch(
        "/lists/no-such-route-list", json={"title": "x"}, headers=_auth(token)
    )
    assert response.status_code == 404


async def test_delete_list_by_owner(client, db):
    token = await _register_and_login(client, "route-lists-user-6")
    created = await client.post("/lists", json={"title": "Delete Me"}, headers=_auth(token))
    slug = created.json()["slug"]

    response = await client.delete(f"/lists/{slug}", headers=_auth(token))
    assert response.status_code == 204

    # Gone afterwards.
    assert (await client.get(f"/lists/{slug}")).status_code == 404


async def test_delete_list_by_non_owner_returns_403(client, db):
    owner_token = await _register_and_login(client, "route-lists-user-7")
    other_token = await _register_and_login(client, "route-lists-user-8")
    created = await client.post(
        "/lists", json={"title": "Protected List"}, headers=_auth(owner_token)
    )
    slug = created.json()["slug"]

    response = await client.delete(f"/lists/{slug}", headers=_auth(other_token))
    assert response.status_code == 403


# ── items ────────────────────────────────────────────────────────────────────


async def test_add_and_remove_items_idempotent(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-list-movie-1"))
    await series_repo.upsert_series(db, _series_data("route-list-series-1"))
    token = await _register_and_login(client, "route-lists-user-9")
    created = await client.post("/lists", json={"title": "Item Ops"}, headers=_auth(token))
    slug = created.json()["slug"]

    r1 = await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-1"},
        headers=_auth(token),
    )
    assert r1.status_code == 200
    assert r1.json()["item_count"] == 1

    r2 = await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "series", "slug": "route-list-series-1"},
        headers=_auth(token),
    )
    assert [i["item_type"] for i in r2.json()["items"]] == ["MOVIE", "SERIES"]

    # Idempotent add.
    r3 = await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-1"},
        headers=_auth(token),
    )
    assert r3.json()["item_count"] == 2

    # Remove.
    r4 = await client.request(
        "DELETE",
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-1"},
        headers=_auth(token),
    )
    assert r4.status_code == 200
    assert [i["slug"] for i in r4.json()["items"]] == ["route-list-series-1"]

    # Idempotent remove (no-op success).
    r5 = await client.request(
        "DELETE",
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-1"},
        headers=_auth(token),
    )
    assert r5.status_code == 200
    assert r5.json()["item_count"] == 1


async def test_add_item_unknown_content_returns_404(client, db):
    token = await _register_and_login(client, "route-lists-user-10")
    created = await client.post("/lists", json={"title": "Ghost Items"}, headers=_auth(token))
    slug = created.json()["slug"]

    response = await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "does-not-exist-movie"},
        headers=_auth(token),
    )
    assert response.status_code == 404


async def test_add_item_by_non_owner_returns_403(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-list-movie-2"))
    owner_token = await _register_and_login(client, "route-lists-user-11")
    other_token = await _register_and_login(client, "route-lists-user-12")
    created = await client.post("/lists", json={"title": "Guarded"}, headers=_auth(owner_token))
    slug = created.json()["slug"]

    response = await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-2"},
        headers=_auth(other_token),
    )
    assert response.status_code == 403


# ── reorder ──────────────────────────────────────────────────────────────────


async def test_reorder_items(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-list-movie-3"))
    await series_repo.upsert_series(db, _series_data("route-list-series-2"))
    token = await _register_and_login(client, "route-lists-user-13")
    created = await client.post("/lists", json={"title": "Reorder Ops"}, headers=_auth(token))
    slug = created.json()["slug"]

    await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-3"},
        headers=_auth(token),
    )
    await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "series", "slug": "route-list-series-2"},
        headers=_auth(token),
    )

    response = await client.put(
        f"/lists/{slug}/items/order",
        json={
            "items": [
                {"item_type": "series", "slug": "route-list-series-2"},
                {"item_type": "movie", "slug": "route-list-movie-3"},
            ]
        },
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert [i["slug"] for i in response.json()["items"]] == [
        "route-list-series-2",
        "route-list-movie-3",
    ]


async def test_reorder_mismatch_returns_422(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-list-movie-4"))
    await series_repo.upsert_series(db, _series_data("route-list-series-3"))
    token = await _register_and_login(client, "route-lists-user-14")
    created = await client.post("/lists", json={"title": "Bad Reorder"}, headers=_auth(token))
    slug = created.json()["slug"]

    await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "movie", "slug": "route-list-movie-4"},
        headers=_auth(token),
    )
    await client.post(
        f"/lists/{slug}/items",
        json={"item_type": "series", "slug": "route-list-series-3"},
        headers=_auth(token),
    )

    response = await client.put(
        f"/lists/{slug}/items/order",
        json={"items": [{"item_type": "movie", "slug": "route-list-movie-4"}]},
        headers=_auth(token),
    )
    assert response.status_code == 422


# ── GET /lists/{slug} visibility ─────────────────────────────────────────────


async def test_get_public_list_is_accessible_anonymously(client, db):
    token = await _register_and_login(client, "route-lists-user-15")
    created = await client.post("/lists", json={"title": "Open Collection"}, headers=_auth(token))
    slug = created.json()["slug"]

    response = await client.get(f"/lists/{slug}")
    assert response.status_code == 200
    assert response.json()["slug"] == slug


async def test_get_private_list_hidden_from_others(client, db):
    owner_token = await _register_and_login(client, "route-lists-user-16")
    other_token = await _register_and_login(client, "route-lists-user-17")
    created = await client.post(
        "/lists",
        json={"title": "Secret Collection", "is_public": False},
        headers=_auth(owner_token),
    )
    slug = created.json()["slug"]

    # Owner can see it.
    assert (await client.get(f"/lists/{slug}", headers=_auth(owner_token))).status_code == 200
    # Anonymous → 404.
    assert (await client.get(f"/lists/{slug}")).status_code == 404
    # Other user → 404.
    assert (await client.get(f"/lists/{slug}", headers=_auth(other_token))).status_code == 404


# ── GET /users/{username}/lists ──────────────────────────────────────────────


async def test_get_user_lists_public_vs_owner(client, db):
    owner_token = await _register_and_login(client, "route-lists-user-18")
    await client.post("/lists", json={"title": "Public A"}, headers=_auth(owner_token))
    await client.post(
        "/lists", json={"title": "Private B", "is_public": False}, headers=_auth(owner_token)
    )

    # Anonymous sees only the public one.
    anon = await client.get("/users/route-lists-user-18/lists")
    assert anon.status_code == 200
    assert anon.json()["total"] == 1
    assert anon.json()["lists"][0]["is_public"] is True

    # Owner sees both.
    owner = await client.get("/users/route-lists-user-18/lists", headers=_auth(owner_token))
    assert owner.json()["total"] == 2


async def test_get_user_lists_unknown_user_returns_404(client, db):
    response = await client.get("/users/nobody-lists-route/lists")
    assert response.status_code == 404
