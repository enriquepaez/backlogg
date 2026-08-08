"""Endpoint tests for GET /feed (activity feed).

Covers auth (401 without token), validation (422 for an invalid tab) and both
tabs (following/popular) with real data. The client fixture + auth helpers are
copied from tests/ratings/test_routes.py (they are not centralized).
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_data(slug: str, title: str = "Feed Route Movie") -> dict:
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


def _series_data(slug: str, title: str = "Feed Route Series") -> dict:
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
    """AsyncClient wired to the FastAPI app, using the test DB session."""
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


# ── auth & validation ─────────────────────────────────────────────────────


async def test_get_feed_without_token_returns_401(client, db):
    response = await client.get("/v1/feed?tab=following")
    assert response.status_code == 401


async def test_get_feed_invalid_tab_returns_422(client, db):
    token = await _register_and_login(client, "feed-route-user-1")
    response = await client.get("/v1/feed?tab=nonsense", headers=_auth_headers(token))
    assert response.status_code == 422


# ── following tab ─────────────────────────────────────────────────────────


async def test_get_feed_following_returns_followed_reviews(client, db):
    await movies_repo.upsert_movie(db, _movie_data("feed-route-movie-1"))
    await series_repo.upsert_series(db, _series_data("feed-route-series-1"))
    caller_token = await _register_and_login(client, "feed-route-caller")
    author_token = await _register_and_login(client, "feed-route-author")

    await client.put(
        "/v1/movies/feed-route-movie-1/rating",
        json={"score": 5, "review_text": "author movie review"},
        headers=_auth_headers(author_token),
    )
    await client.put(
        "/v1/series/feed-route-series-1/rating",
        json={"score": 4, "review_text": "author series review"},
        headers=_auth_headers(author_token),
    )
    await client.post("/v1/users/feed-route-author/follow", headers=_auth_headers(caller_token))

    response = await client.get("/v1/feed?tab=following", headers=_auth_headers(caller_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    item_types = {entry["item"]["item_type"] for entry in body["items"]}
    assert item_types == {"MOVIE", "SERIES"}
    assert body["items"][0]["author"]["username"] == "feed-route-author"


async def test_get_feed_following_no_follows_returns_empty(client, db):
    token = await _register_and_login(client, "feed-route-loner")
    response = await client.get("/v1/feed?tab=following", headers=_auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


# ── popular tab ───────────────────────────────────────────────────────────


async def test_get_feed_popular_returns_recent_reviews_with_like_count(client, db):
    await movies_repo.upsert_movie(db, _movie_data("feed-route-movie-2"))
    author_token = await _register_and_login(client, "feed-route-author-2")
    liker_token = await _register_and_login(client, "feed-route-liker")

    put_response = await client.put(
        "/v1/movies/feed-route-movie-2/rating",
        json={"score": 5, "review_text": "popular review"},
        headers=_auth_headers(author_token),
    )
    rating_id = put_response.json()["id"]
    await client.post(f"/v1/ratings/{rating_id}/like", headers=_auth_headers(liker_token))

    response = await client.get(
        "/v1/feed?tab=popular&limit=100", headers=_auth_headers(liker_token)
    )
    assert response.status_code == 200
    body = response.json()
    # The popular tab is global (all recent reviews), and rating routes commit
    # mid-test, so other tests' committed reviews may also appear. Assert on our
    # own entry rather than the total.
    entry = next(e for e in body["items"] if e["item"]["slug"] == "feed-route-movie-2")
    assert entry["review_text"] == "popular review"
    assert entry["like_count"] == 1
    assert entry["author"]["username"] == "feed-route-author-2"
