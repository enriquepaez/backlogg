"""Endpoint tests for the ratings & reviews feature.

Covers:
- PUT/DELETE/GET .../rating(s) on all four content routers (movies is
  exercised in full; series/books/games get a happy-path symmetry check).
- POST/DELETE /ratings/{id}/like (auth, idempotent, 404).
- GET /users/{username}/reviews (public, cross-type).
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _movie_data(slug: str, title: str = "Route Rating Movie") -> dict:
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


def _series_data(slug: str, title: str = "Route Rating Series") -> dict:
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


def _book_data(slug: str, title: str = "Route Rating Book") -> dict:
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


def _game_data(slug: str, title: str = "Route Rating Game") -> dict:
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
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )
    login = await client.post("/auth/login", json={"username": username, "password": "s3cret-pw"})
    return login.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── PUT /movies/{slug}/rating ────────────────────────────────────────────


async def test_put_movie_rating_without_token_returns_401(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-1"))
    response = await client.put(
        "/movies/route-rating-movie-1/rating", json={"score": 4, "review_text": "Great"}
    )
    assert response.status_code == 401


async def test_put_movie_rating_upserts_and_returns_200(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-2"))
    token = await _register_and_login(client, "route-rating-user-1")

    response = await client.put(
        "/movies/route-rating-movie-2/rating",
        json={"score": 5, "review_text": "Masterpiece"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 5
    assert body["review_text"] == "Masterpiece"
    assert body["like_count"] == 0
    assert body["user"]["username"] == "route-rating-user-1"


async def test_put_movie_rating_invalid_score_returns_422(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-3"))
    token = await _register_and_login(client, "route-rating-user-2")

    response = await client.put(
        "/movies/route-rating-movie-3/rating",
        json={"score": 6, "review_text": "Too high"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422


async def test_put_movie_rating_slug_not_found_returns_404(client, db):
    token = await _register_and_login(client, "route-rating-user-3")

    response = await client.put(
        "/movies/no-such-movie-route-rating/rating",
        json={"score": 3, "review_text": None},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


# ── DELETE /movies/{slug}/rating ─────────────────────────────────────────


async def test_delete_movie_rating_without_token_returns_401(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-4"))
    response = await client.delete("/movies/route-rating-movie-4/rating")
    assert response.status_code == 401


async def test_delete_movie_rating_removes_it(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-5"))
    token = await _register_and_login(client, "route-rating-user-4")

    await client.put(
        "/movies/route-rating-movie-5/rating",
        json={"score": 3, "review_text": None},
        headers=_auth_headers(token),
    )
    response = await client.delete(
        "/movies/route-rating-movie-5/rating", headers=_auth_headers(token)
    )
    assert response.status_code == 204

    movie = await movies_repo.get_movie_by_slug(db, "route-rating-movie-5")
    assert movie.rating_count_internal == 0


async def test_delete_movie_rating_not_found_returns_404(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-6"))
    token = await _register_and_login(client, "route-rating-user-5")

    response = await client.delete(
        "/movies/route-rating-movie-6/rating", headers=_auth_headers(token)
    )
    assert response.status_code == 404


# ── GET /movies/{slug}/ratings ───────────────────────────────────────────


async def test_get_movie_ratings_public_paginated_with_like_count(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-7"))
    author_token = await _register_and_login(client, "route-rating-user-6")
    liker_token = await _register_and_login(client, "route-rating-user-7")

    put_response = await client.put(
        "/movies/route-rating-movie-7/rating",
        json={"score": 5, "review_text": "So good"},
        headers=_auth_headers(author_token),
    )
    rating_id = put_response.json()["id"]

    await client.post(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))

    response = await client.get("/movies/route-rating-movie-7/ratings")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["like_count"] == 1
    assert body["items"][0]["review_text"] == "So good"


async def test_get_movie_ratings_slug_not_found_returns_404(client, db):
    response = await client.get("/movies/no-such-movie-route-ratings-list/ratings")
    assert response.status_code == 404


# ── POST/DELETE /ratings/{id}/like ───────────────────────────────────────


async def test_post_like_without_token_returns_401(client, db):
    response = await client.post("/ratings/1/like")
    assert response.status_code == 401


async def test_post_like_rating_not_found_returns_404(client, db):
    token = await _register_and_login(client, "route-rating-user-8")
    response = await client.post("/ratings/999999999/like", headers=_auth_headers(token))
    assert response.status_code == 404


async def test_post_like_idempotent_no_duplicate(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-8"))
    author_token = await _register_and_login(client, "route-rating-user-9")
    liker_token = await _register_and_login(client, "route-rating-user-10")

    put_response = await client.put(
        "/movies/route-rating-movie-8/rating",
        json={"score": 4, "review_text": "Nice"},
        headers=_auth_headers(author_token),
    )
    rating_id = put_response.json()["id"]

    first = await client.post(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))
    second = await client.post(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))
    assert first.status_code == 204
    assert second.status_code == 204

    ratings = await client.get("/movies/route-rating-movie-8/ratings")
    assert ratings.json()["items"][0]["like_count"] == 1


async def test_delete_like_idempotent(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-9"))
    author_token = await _register_and_login(client, "route-rating-user-11")
    liker_token = await _register_and_login(client, "route-rating-user-12")

    put_response = await client.put(
        "/movies/route-rating-movie-9/rating",
        json={"score": 4, "review_text": "Nice"},
        headers=_auth_headers(author_token),
    )
    rating_id = put_response.json()["id"]
    await client.post(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))

    first = await client.delete(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))
    second = await client.delete(f"/ratings/{rating_id}/like", headers=_auth_headers(liker_token))
    assert first.status_code == 204
    assert second.status_code == 204

    ratings = await client.get("/movies/route-rating-movie-9/ratings")
    assert ratings.json()["items"][0]["like_count"] == 0


# ── GET /users/{username}/reviews ────────────────────────────────────────


async def test_get_user_reviews_cross_type_public(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-10"))
    await series_repo.upsert_series(db, _series_data("route-rating-series-1"))
    token = await _register_and_login(client, "route-rating-user-13")

    await client.put(
        "/movies/route-rating-movie-10/rating",
        json={"score": 5, "review_text": "Movie review"},
        headers=_auth_headers(token),
    )
    await client.put(
        "/series/route-rating-series-1/rating",
        json={"score": 4, "review_text": "Series review"},
        headers=_auth_headers(token),
    )

    response = await client.get("/users/route-rating-user-13/reviews")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    item_types = {item["item"]["item_type"] for item in body["items"]}
    assert item_types == {"MOVIE", "SERIES"}


async def test_get_user_reviews_user_not_found_returns_404(client, db):
    response = await client.get("/users/nobody-has-reviews-ever/reviews")
    assert response.status_code == 404


# ── Symmetry: series/books/games PUT + DELETE + GET ratings ─────────────


async def test_series_rating_put_delete_get_symmetry(client, db):
    await series_repo.upsert_series(db, _series_data("route-rating-series-2"))
    token = await _register_and_login(client, "route-rating-user-14")

    put_response = await client.put(
        "/series/route-rating-series-2/rating",
        json={"score": 4, "review_text": "Solid"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200
    assert put_response.json()["score"] == 4

    get_response = await client.get("/series/route-rating-series-2/ratings")
    assert get_response.status_code == 200
    assert get_response.json()["total"] == 1

    delete_response = await client.delete(
        "/series/route-rating-series-2/rating", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204


async def test_book_rating_put_delete_get_symmetry(client, db):
    await books_repo.upsert_book(db, _book_data("route-rating-book-1"))
    token = await _register_and_login(client, "route-rating-user-15")

    put_response = await client.put(
        "/books/route-rating-book-1/rating",
        json={"score": 3, "review_text": "Decent"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200
    assert put_response.json()["score"] == 3

    get_response = await client.get("/books/route-rating-book-1/ratings")
    assert get_response.status_code == 200
    assert get_response.json()["total"] == 1

    delete_response = await client.delete(
        "/books/route-rating-book-1/rating", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204


async def test_game_rating_put_delete_get_symmetry(client, db):
    await games_repo.upsert_game(db, _game_data("route-rating-game-1"))
    token = await _register_and_login(client, "route-rating-user-16")

    put_response = await client.put(
        "/games/route-rating-game-1/rating",
        json={"score": 5, "review_text": "Fantastic"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200
    assert put_response.json()["score"] == 5

    get_response = await client.get("/games/route-rating-game-1/ratings")
    assert get_response.status_code == 200
    assert get_response.json()["total"] == 1

    delete_response = await client.delete(
        "/games/route-rating-game-1/rating", headers=_auth_headers(token)
    )
    assert delete_response.status_code == 204


# ── PUT rating then GET /{tipo}/{slug} exposes the recalculated aggregate ──
#
# Regression coverage for the gap found in QA manual: rating_internal /
# rating_count_internal must reflect the *real* recalculated value coming
# back through GET /{tipo}/{slug} (not just the None/0 default on fixtures
# that never receive a rating). A single rating means rating_internal must
# equal that rating's score exactly and rating_count_internal must be 1.


async def test_put_movie_rating_then_get_detail_reflects_recalculated_aggregate(client, db):
    await movies_repo.upsert_movie(db, _movie_data("route-rating-movie-detail-1"))
    token = await _register_and_login(client, "route-rating-user-17")

    put_response = await client.put(
        "/movies/route-rating-movie-detail-1/rating",
        json={"score": 4, "review_text": "Good"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200

    detail_response = await client.get("/movies/route-rating-movie-detail-1")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["rating_internal"] == 4
    assert body["rating_count_internal"] == 1


async def test_put_series_rating_then_get_detail_reflects_recalculated_aggregate(client, db):
    await series_repo.upsert_series(db, _series_data("route-rating-series-detail-1"))
    token = await _register_and_login(client, "route-rating-user-18")

    put_response = await client.put(
        "/series/route-rating-series-detail-1/rating",
        json={"score": 5, "review_text": "Excellent"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200

    detail_response = await client.get("/series/route-rating-series-detail-1")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["rating_internal"] == 5
    assert body["rating_count_internal"] == 1


async def test_put_book_rating_then_get_detail_reflects_recalculated_aggregate(client, db):
    await books_repo.upsert_book(db, _book_data("route-rating-book-detail-1"))
    token = await _register_and_login(client, "route-rating-user-19")

    put_response = await client.put(
        "/books/route-rating-book-detail-1/rating",
        json={"score": 3, "review_text": "Fine"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200

    detail_response = await client.get("/books/route-rating-book-detail-1")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["rating_internal"] == 3
    assert body["rating_count_internal"] == 1


async def test_put_game_rating_then_get_detail_reflects_recalculated_aggregate(client, db):
    await games_repo.upsert_game(db, _game_data("route-rating-game-detail-1"))
    token = await _register_and_login(client, "route-rating-user-20")

    put_response = await client.put(
        "/games/route-rating-game-detail-1/rating",
        json={"score": 2, "review_text": "Meh"},
        headers=_auth_headers(token),
    )
    assert put_response.status_code == 200

    detail_response = await client.get("/games/route-rating-game-detail-1")
    assert detail_response.status_code == 200
    body = detail_response.json()
    assert body["rating_internal"] == 2
    assert body["rating_count_internal"] == 1
