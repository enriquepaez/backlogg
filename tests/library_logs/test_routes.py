"""Endpoint tests for the activity log feature (feature 52).

Covers:
- POST/GET /{type}/{slug}/log on all four content routers (movies in full;
  series/books/games get a happy-path symmetry check).
- GET /users/{username}/log (public, paginated, cross-type).
- DELETE /log/{id}.
- 401/404/422 error paths, multiple logs per item, and non-interference with
  user_ratings.
"""

from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_data(slug: str, title: str = "Route Log Movie") -> dict:
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


def _series_data(slug: str, title: str = "Route Log Series") -> dict:
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


def _book_data(slug: str, title: str = "Route Log Book") -> dict:
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


def _game_data(slug: str, title: str = "Route Log Game") -> dict:
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
        "/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )
    login = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-pw"}
    )
    return login.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── POST /movies/{slug}/log ──────────────────────────────────────────────


async def test_post_log_without_token_returns_401(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-1"))
    response = await client.post("/v1/movies/route-log-movie-1/log", json={})
    assert response.status_code == 401


async def test_post_log_creates_with_default_logged_on(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-2"))
    token = await _register_and_login(client, "route-log-user-1")

    response = await client.post(
        "/v1/movies/route-log-movie-2/log", json={}, headers=_auth_headers(token)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["item_type"] == "MOVIE"
    assert body["slug"] == "route-log-movie-2"
    assert body["logged_on"] == date.today().isoformat()
    assert body["rewatch"] is False
    assert body["note"] is None


async def test_post_log_with_explicit_fields(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-3"))
    token = await _register_and_login(client, "route-log-user-2")

    response = await client.post(
        "/v1/movies/route-log-movie-3/log",
        json={"logged_on": "2024-05-01", "rewatch": True, "note": "Second watch"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["logged_on"] == "2024-05-01"
    assert body["rewatch"] is True
    assert body["note"] == "Second watch"


async def test_post_log_allows_multiple_entries_same_item(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-4"))
    token = await _register_and_login(client, "route-log-user-3")

    first = await client.post(
        "/v1/movies/route-log-movie-4/log",
        json={"logged_on": "2024-01-01"},
        headers=_auth_headers(token),
    )
    second = await client.post(
        "/v1/movies/route-log-movie-4/log",
        json={"logged_on": "2024-06-01", "rewatch": True},
        headers=_auth_headers(token),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    listing = await client.get("/v1/movies/route-log-movie-4/log")
    assert listing.json()["total"] == 2


async def test_post_log_future_date_returns_422(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-5"))
    token = await _register_and_login(client, "route-log-user-4")

    future = (date.today() + timedelta(days=5)).isoformat()
    response = await client.post(
        "/v1/movies/route-log-movie-5/log",
        json={"logged_on": future},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


async def test_post_log_slug_not_found_returns_404(client, db):
    token = await _register_and_login(client, "route-log-user-5")
    response = await client.post(
        "/v1/movies/no-such-movie-log/log", json={}, headers=_auth_headers(token)
    )
    assert response.status_code == 404


# ── GET /movies/{slug}/log ───────────────────────────────────────────────


async def test_get_item_log_public_no_auth(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-6"))
    token = await _register_and_login(client, "route-log-user-6")
    await client.post(
        "/v1/movies/route-log-movie-6/log",
        json={"logged_on": "2024-01-01"},
        headers=_auth_headers(token),
    )

    response = await client.get("/v1/movies/route-log-movie-6/log")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["logged_on"] == "2024-01-01"


async def test_get_item_log_slug_not_found_returns_404(client, db):
    response = await client.get("/v1/movies/no-such-movie-log-2/log")
    assert response.status_code == 404


# ── DELETE /log/{id} ─────────────────────────────────────────────────────


async def test_delete_log_without_token_returns_401(client, db):
    response = await client.delete("/v1/log/1")
    assert response.status_code == 401


async def test_delete_log_removes_own_entry(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-7"))
    token = await _register_and_login(client, "route-log-user-7")
    created = await client.post(
        "/v1/movies/route-log-movie-7/log", json={}, headers=_auth_headers(token)
    )
    log_id = created.json()["id"]

    response = await client.delete(f"/v1/log/{log_id}", headers=_auth_headers(token))
    assert response.status_code == 204

    listing = await client.get("/v1/movies/route-log-movie-7/log")
    assert listing.json()["total"] == 0


async def test_delete_log_not_found_returns_404(client, db):
    token = await _register_and_login(client, "route-log-user-8")
    response = await client.delete("/v1/log/999999", headers=_auth_headers(token))
    assert response.status_code == 404


async def test_delete_log_owned_by_another_user_returns_404(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-8"))
    owner_token = await _register_and_login(client, "route-log-user-9")
    other_token = await _register_and_login(client, "route-log-user-10")

    created = await client.post(
        "/v1/movies/route-log-movie-8/log", json={}, headers=_auth_headers(owner_token)
    )
    log_id = created.json()["id"]

    response = await client.delete(f"/v1/log/{log_id}", headers=_auth_headers(other_token))
    assert response.status_code == 404


# ── GET /users/{username}/log ────────────────────────────────────────────


async def test_get_user_log_public_cross_type(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-9"))
    await series_repo.upsert_series(db, _series_data("route-log-series-1"))
    token = await _register_and_login(client, "route-log-user-11")

    await client.post(
        "/v1/movies/route-log-movie-9/log",
        json={"logged_on": "2024-01-01"},
        headers=_auth_headers(token),
    )
    await client.post(
        "/v1/series/route-log-series-1/log",
        json={"logged_on": "2024-02-01"},
        headers=_auth_headers(token),
    )

    response = await client.get("/v1/users/route-log-user-11/log")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    item_types = {entry["item"]["item_type"] for entry in body["items"]}
    assert item_types == {"MOVIE", "SERIES"}
    sample = body["items"][0]
    assert set(sample["item"].keys()) == {"item_type", "title", "slug", "poster_url"}
    assert "logged_on" in sample
    assert "rewatch" in sample


async def test_get_user_log_unknown_user_returns_404(client, db):
    response = await client.get("/v1/users/nobody-log-ever/log")
    assert response.status_code == 404


# ── Symmetry: series/books/games POST + GET ──────────────────────────────


async def test_series_log_post_get_symmetry(client, db):
    await series_repo.upsert_series(db, _series_data("route-log-series-2"))
    token = await _register_and_login(client, "route-log-user-12")

    post = await client.post(
        "/v1/series/route-log-series-2/log", json={}, headers=_auth_headers(token)
    )
    assert post.status_code == 201
    assert post.json()["item_type"] == "SERIES"

    get = await client.get("/v1/series/route-log-series-2/log")
    assert get.status_code == 200
    assert get.json()["total"] == 1


async def test_book_log_post_get_symmetry(client, db):
    await books_repo.upsert_book(db, _book_data("route-log-book-1"))
    token = await _register_and_login(client, "route-log-user-13")

    post = await client.post(
        "/v1/books/route-log-book-1/log", json={"note": "Reread"}, headers=_auth_headers(token)
    )
    assert post.status_code == 201
    assert post.json()["item_type"] == "BOOK"
    assert post.json()["note"] == "Reread"

    get = await client.get("/v1/books/route-log-book-1/log")
    assert get.status_code == 200
    assert get.json()["total"] == 1


async def test_game_log_post_get_symmetry(client, db):
    await games_repo.upsert_game(db, _game_data("route-log-game-1"))
    token = await _register_and_login(client, "route-log-user-14")

    post = await client.post(
        "/v1/games/route-log-game-1/log",
        json={"rewatch": True},
        headers=_auth_headers(token),
    )
    assert post.status_code == 201
    assert post.json()["item_type"] == "GAME"
    assert post.json()["rewatch"] is True

    get = await client.get("/v1/games/route-log-game-1/log")
    assert get.status_code == 200
    assert get.json()["total"] == 1


# ── Non-interference with user_ratings (feature 28) ──────────────────────


async def test_log_creation_does_not_create_or_modify_rating(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-10"))
    token = await _register_and_login(client, "route-log-user-15")

    await client.post("/v1/movies/route-log-movie-10/log", json={}, headers=_auth_headers(token))

    ratings = await client.get("/v1/movies/route-log-movie-10/ratings")
    assert ratings.status_code == 200
    assert ratings.json()["total"] == 0


async def test_rating_creation_does_not_create_log(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-log-movie-11"))
    token = await _register_and_login(client, "route-log-user-16")

    await client.put(
        "/v1/movies/route-log-movie-11/rating",
        json={"score": 5, "review_text": "Loved it"},
        headers=_auth_headers(token),
    )

    logs = await client.get("/v1/movies/route-log-movie-11/log")
    assert logs.status_code == 200
    assert logs.json()["total"] == 0
