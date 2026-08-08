"""Endpoint tests for the user library feature.

Covers:
- PUT/DELETE /{type}/{slug}/library on all four content routers (movies in
  full; series/books/games get a happy-path symmetry check).
- GET /users/{username}/library (public, paginated, filters).
- viewer_status on GET /{type}/{slug} (with and without auth).
- library_counts on GET /users/{username}.
- 401/404/422 error paths.
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_data(slug: str, title: str = "Route Library Movie") -> dict:
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


def _series_data(slug: str, title: str = "Route Library Series") -> dict:
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


def _book_data(slug: str, title: str = "Route Library Book") -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": date(2020, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_data(slug: str, title: str = "Route Library Game") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": date(2020, 1, 1),
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


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── PUT /movies/{slug}/library ───────────────────────────────────────────


async def test_put_library_without_token_returns_401(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-1"))
    response = await client.put("/movies/route-library-movie-1/library", json={"status": "want"})
    assert response.status_code == 401


async def test_put_library_upserts_and_returns_200(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-2"))
    token = await _register_and_login(client, "route-library-user-1")

    response = await client.put(
        "/movies/route-library-movie-2/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "want"
    assert body["item_type"] == "MOVIE"
    assert body["slug"] == "route-library-movie-2"

    # Upsert to a new status.
    response2 = await client.put(
        "/movies/route-library-movie-2/library",
        json={"status": "completed"},
        headers=_auth_headers(token),
    )
    assert response2.status_code == 200
    assert response2.json()["status"] == "completed"


async def test_put_library_invalid_status_returns_422(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-3"))
    token = await _register_and_login(client, "route-library-user-2")

    response = await client.put(
        "/movies/route-library-movie-3/library",
        json={"status": "reading"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


async def test_put_library_slug_not_found_returns_404(client, db):
    token = await _register_and_login(client, "route-library-user-3")
    response = await client.put(
        "/movies/no-such-movie-library/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


# ── DELETE /movies/{slug}/library ────────────────────────────────────────


async def test_delete_library_without_token_returns_401(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-4"))
    response = await client.delete("/movies/route-library-movie-4/library")
    assert response.status_code == 401


async def test_delete_library_removes_entry(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-5"))
    token = await _register_and_login(client, "route-library-user-4")

    await client.put(
        "/movies/route-library-movie-5/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    response = await client.delete(
        "/movies/route-library-movie-5/library", headers=_auth_headers(token)
    )
    assert response.status_code == 204


async def test_delete_library_not_found_returns_404(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-6"))
    token = await _register_and_login(client, "route-library-user-5")

    response = await client.delete(
        "/movies/route-library-movie-6/library", headers=_auth_headers(token)
    )
    assert response.status_code == 404


# ── GET /users/{username}/library ────────────────────────────────────────


async def test_get_user_library_public_cross_type(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-7"))
    await series_repo.upsert_series(db, _series_data("route-library-series-1"))
    token = await _register_and_login(client, "route-library-user-6")

    await client.put(
        "/movies/route-library-movie-7/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    await client.put(
        "/series/route-library-series-1/library",
        json={"status": "completed"},
        headers=_auth_headers(token),
    )

    # No auth required for reading.
    response = await client.get("/users/route-library-user-6/library")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    item_types = {entry["item"]["item_type"] for entry in body["items"]}
    assert item_types == {"MOVIE", "SERIES"}
    # Each entry surfaces the item shape + status.
    sample = body["items"][0]
    assert set(sample["item"].keys()) == {
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
    }
    assert "status" in sample


async def test_get_user_library_filter_by_status_and_type(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-8"))
    await series_repo.upsert_series(db, _series_data("route-library-series-2"))
    token = await _register_and_login(client, "route-library-user-7")

    await client.put(
        "/movies/route-library-movie-8/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    await client.put(
        "/series/route-library-series-2/library",
        json={"status": "completed"},
        headers=_auth_headers(token),
    )

    by_status = await client.get("/users/route-library-user-7/library?status=want")
    assert by_status.status_code == 200
    assert by_status.json()["total"] == 1
    assert by_status.json()["items"][0]["item"]["item_type"] == "MOVIE"

    by_type = await client.get("/users/route-library-user-7/library?type=series")
    assert by_type.status_code == 200
    assert by_type.json()["total"] == 1
    assert by_type.json()["items"][0]["item"]["item_type"] == "SERIES"


async def test_get_user_library_invalid_status_filter_returns_422(client, db):
    await _register_and_login(client, "route-library-user-8")
    response = await client.get("/users/route-library-user-8/library?status=bogus")
    assert response.status_code == 422


async def test_get_user_library_unknown_user_returns_404(client, db):
    response = await client.get("/users/nobody-library-ever/library")
    assert response.status_code == 404


# ── viewer_status on GET /{type}/{slug} ──────────────────────────────────


async def test_get_movie_viewer_status_null_without_auth(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-9"))
    token = await _register_and_login(client, "route-library-user-9")
    await client.put(
        "/movies/route-library-movie-9/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )

    # Anonymous caller — viewer_status must be null even though someone else set it.
    response = await client.get("/movies/route-library-movie-9")
    assert response.status_code == 200
    assert response.json()["viewer_status"] is None


async def test_get_movie_viewer_status_reflects_caller_entry(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-10"))
    token = await _register_and_login(client, "route-library-user-10")
    await client.put(
        "/movies/route-library-movie-10/library",
        json={"status": "in_progress"},
        headers=_auth_headers(token),
    )

    response = await client.get("/movies/route-library-movie-10", headers=_auth_headers(token))
    assert response.status_code == 200
    assert response.json()["viewer_status"] == "in_progress"


async def test_get_movie_viewer_status_null_when_authed_without_entry(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-11"))
    token = await _register_and_login(client, "route-library-user-11")

    response = await client.get("/movies/route-library-movie-11", headers=_auth_headers(token))
    assert response.status_code == 200
    assert response.json()["viewer_status"] is None


# ── library_counts on GET /users/{username} ──────────────────────────────


async def test_get_user_profile_includes_library_counts(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-library-movie-12"))
    await series_repo.upsert_series(db, _series_data("route-library-series-3"))
    token = await _register_and_login(client, "route-library-user-12")

    await client.put(
        "/movies/route-library-movie-12/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    await client.put(
        "/series/route-library-series-3/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )

    response = await client.get("/users/route-library-user-12")
    assert response.status_code == 200
    counts = response.json()["library_counts"]
    assert counts == {"want": 2, "in_progress": 0, "completed": 0, "dropped": 0}


# ── Symmetry: series/books/games PUT + DELETE ────────────────────────────


async def test_series_library_put_delete_symmetry(client, db):
    await series_repo.upsert_series(db, _series_data("route-library-series-4"))
    token = await _register_and_login(client, "route-library-user-13")

    put = await client.put(
        "/series/route-library-series-4/library",
        json={"status": "want"},
        headers=_auth_headers(token),
    )
    assert put.status_code == 200
    assert put.json()["status"] == "want"

    delete = await client.delete(
        "/series/route-library-series-4/library", headers=_auth_headers(token)
    )
    assert delete.status_code == 204


async def test_book_library_put_delete_symmetry(client, db):
    await books_repo.upsert_book(db, _book_data("route-library-book-1"))
    token = await _register_and_login(client, "route-library-user-14")

    put = await client.put(
        "/books/route-library-book-1/library",
        json={"status": "completed"},
        headers=_auth_headers(token),
    )
    assert put.status_code == 200
    assert put.json()["status"] == "completed"

    # viewer_status exposed on the book detail for the caller.
    detail = await client.get("/books/route-library-book-1", headers=_auth_headers(token))
    assert detail.status_code == 200
    assert detail.json()["viewer_status"] == "completed"

    delete = await client.delete(
        "/books/route-library-book-1/library", headers=_auth_headers(token)
    )
    assert delete.status_code == 204


async def test_game_library_put_delete_symmetry(client, db):
    await games_repo.upsert_game(db, _game_data("route-library-game-1"))
    token = await _register_and_login(client, "route-library-user-15")

    put = await client.put(
        "/games/route-library-game-1/library",
        json={"status": "dropped"},
        headers=_auth_headers(token),
    )
    assert put.status_code == 200
    assert put.json()["status"] == "dropped"

    detail = await client.get("/games/route-library-game-1", headers=_auth_headers(token))
    assert detail.status_code == 200
    assert detail.json()["viewer_status"] == "dropped"

    delete = await client.delete(
        "/games/route-library-game-1/library", headers=_auth_headers(token)
    )
    assert delete.status_code == 204
