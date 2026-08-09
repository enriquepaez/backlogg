"""Tests for DELETE /users/me (feature 42 — account_deletion).

Covers the acceptance criteria: auth requirement (401), happy-path 204,
freed username/email, refresh-token invalidation (endpoint level), and — at the
DB level against real Postgres — the ON DELETE CASCADE across every table that
references users.id plus the recompute of the catalog aggregates for items the
deleted user had rated.
"""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backlogg.follows.models import Follow
from backlogg.library.models import LibraryEntry
from backlogg.lists.models import UserList
from backlogg.main import app
from backlogg.movies.models import Movie
from backlogg.movies.repository import upsert_movie
from backlogg.notifications.models import Notification
from backlogg.ratings.models import ReviewLike, UserRating
from backlogg.users import service
from backlogg.users.models import AccountToken, RefreshToken, User
from backlogg.users.repository import create_user


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


def _register_payload(username: str, email: str, password: str = "s3cret-password") -> dict:
    return {"username": username, "email": email, "password": password}


async def _register_and_login(client, username: str, email: str) -> dict:
    """Register a user, log in, and return the token pair dict."""
    await client.post("/v1/auth/register", json=_register_payload(username, email))
    login = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-password"}
    )
    return login.json()


def _movie_data(slug: str, title: str = "Deletion Movie") -> dict:
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


# ── Endpoint: auth requirement ───────────────────────────────────────────────


async def test_delete_me_without_token_returns_401(client):
    response = await client.delete("/v1/users/me")
    assert response.status_code == 401


async def test_delete_me_with_invalid_token_returns_401(client):
    response = await client.delete(
        "/v1/users/me", headers={"Authorization": "Bearer not-a-valid-token"}
    )
    assert response.status_code == 401


# ── Endpoint: happy path + re-registration ───────────────────────────────────


async def test_delete_me_returns_204_and_removes_account(client):
    tokens = await _register_and_login(client, "del-happy-user", "del-happy@example.com")
    access = tokens["access_token"]

    response = await client.delete("/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert response.status_code == 204
    assert response.content == b""

    # The public profile no longer resolves.
    profile = await client.get("/v1/users/del-happy-user")
    assert profile.status_code == 404


async def test_delete_me_frees_username_and_email_for_reregistration(client):
    tokens = await _register_and_login(client, "del-reuse-user", "del-reuse@example.com")
    await client.delete(
        "/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    # Same username AND email can be registered again.
    again = await client.post(
        "/v1/auth/register", json=_register_payload("del-reuse-user", "del-reuse@example.com")
    )
    assert again.status_code == 201


# ── Endpoint: refresh tokens invalidated ─────────────────────────────────────


async def test_refresh_after_deletion_returns_401(client):
    tokens = await _register_and_login(client, "del-refresh-user", "del-refresh@example.com")

    # Sanity: the refresh token works before deletion.
    ok = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ok.status_code == 200
    refresh_after_rotate = ok.json()["refresh_token"]

    login2 = await client.post(
        "/v1/auth/login", json={"username": "del-refresh-user", "password": "s3cret-password"}
    )
    access = login2.json()["access_token"]
    await client.delete("/v1/users/me", headers={"Authorization": f"Bearer {access}"})

    # Neither the rotated token nor a freshly issued one can refresh anymore.
    dead = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_after_rotate})
    assert dead.status_code == 401


# ── DB level: cascade across every referencing table ─────────────────────────


async def test_delete_user_cascades_all_related_rows(db):
    # Two users so we can also assert the *other* user's data survives.
    victim = await create_user(
        db,
        {
            "username": "cascade-victim",
            "email": "cascade-victim@example.com",
            "password_hash": "hash",
            "display_name": "Victim",
        },
    )
    other = await create_user(
        db,
        {
            "username": "cascade-other",
            "email": "cascade-other@example.com",
            "password_hash": "hash",
            "display_name": "Other",
        },
    )
    movie = await upsert_movie(db, _movie_data("cascade-movie-1"))

    victim_rating = UserRating(
        user_id=victim.id, item_type="MOVIE", item_id=movie.id, score=4, review_text="great"
    )
    db.add(victim_rating)
    await db.flush()

    # The other user likes the victim's review (review_like tied to victim's rating).
    db.add(ReviewLike(user_id=other.id, rating_id=victim_rating.id))
    # Follows in both directions.
    db.add(Follow(follower_id=victim.id, followed_id=other.id))
    db.add(Follow(follower_id=other.id, followed_id=victim.id))
    # Library entry, list, notifications (recipient + actor), tokens.
    db.add(LibraryEntry(user_id=victim.id, item_type="MOVIE", item_id=movie.id, status="want"))
    db.add(UserList(user_id=victim.id, slug="my-list", title="My List"))
    db.add(Notification(recipient_id=victim.id, actor_id=other.id, type="new_follower"))
    db.add(Notification(recipient_id=other.id, actor_id=victim.id, type="new_follower"))
    db.add(
        RefreshToken(
            user_id=victim.id,
            token_hash="cascade-refresh-hash",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.add(
        AccountToken(
            user_id=victim.id,
            token_hash="cascade-account-hash",
            purpose="email_verify",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()

    victim_id = victim.id
    await service.delete_current_user(db, victim)

    async def count(model, **filters):
        stmt = select(func.count()).select_from(model)
        for attr, value in filters.items():
            stmt = stmt.where(getattr(model, attr) == value)
        result = await db.execute(stmt)
        return result.scalar_one()

    # The victim and everything referencing them is gone.
    assert await count(User, id=victim_id) == 0
    assert await count(UserRating, user_id=victim_id) == 0
    assert await count(ReviewLike, user_id=other.id, rating_id=victim_rating.id) == 0
    assert await count(Follow, follower_id=victim_id) == 0
    assert await count(Follow, followed_id=victim_id) == 0
    assert await count(LibraryEntry, user_id=victim_id) == 0
    assert await count(UserList, user_id=victim_id) == 0
    assert await count(Notification, recipient_id=victim_id) == 0
    assert await count(Notification, actor_id=victim_id) == 0
    assert await count(RefreshToken, user_id=victim_id) == 0
    assert await count(AccountToken, user_id=victim_id) == 0

    # The other user is untouched.
    assert await count(User, id=other.id) == 1


# ── DB level: aggregate recompute after deletion ─────────────────────────────


async def test_delete_user_recomputes_item_aggregates(db):
    keeper = await create_user(
        db,
        {
            "username": "agg-keeper",
            "email": "agg-keeper@example.com",
            "password_hash": "hash",
            "display_name": "Keeper",
        },
    )
    leaver = await create_user(
        db,
        {
            "username": "agg-leaver",
            "email": "agg-leaver@example.com",
            "password_hash": "hash",
            "display_name": "Leaver",
        },
    )
    movie = await upsert_movie(db, _movie_data("agg-movie-1", "Aggregate Movie"))

    # Two scores: keeper=2, leaver=4 → avg 3.00, count 2.
    db.add(UserRating(user_id=keeper.id, item_type="MOVIE", item_id=movie.id, score=2))
    db.add(UserRating(user_id=leaver.id, item_type="MOVIE", item_id=movie.id, score=4))
    await db.flush()

    from backlogg.ratings.repository import recalculate_item_aggregates

    await recalculate_item_aggregates(db, "MOVIE", movie.id)
    await db.flush()
    refreshed = await db.get(Movie, movie.id)
    await db.refresh(refreshed)
    assert float(refreshed.rating_internal) == 3.0
    assert refreshed.rating_count_internal == 2

    # Deleting the leaver must recompute the movie to the keeper's score alone.
    await service.delete_current_user(db, leaver)

    refreshed = await db.get(Movie, movie.id)
    await db.refresh(refreshed)
    assert float(refreshed.rating_internal) == 2.0
    assert refreshed.rating_count_internal == 1
