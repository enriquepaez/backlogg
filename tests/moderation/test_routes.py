"""Endpoint tests for the content_moderation feature (feature 44).

Covers:
- POST /admin/reviews/{id}/hide + /unhide (X-API-Key, 404, idempotent).
- Hidden reviews are excluded from the item ratings list, the per-user reviews
  list and the feed, and stop counting toward rating_internal/count_internal.
- POST /admin/users/{username}/ban + /unban (X-API-Key, 404, idempotent).
- A banned user cannot log in or refresh (both 401) and their reviews are
  excluded from the same listing surfaces + aggregates.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies.repository import upsert_movie

_VALID_KEY = "test-admin-secret"


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the app + test DB, with a known admin X-API-Key."""
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


def _movie_data(slug: str, title: str = "Moderation Movie") -> dict:
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


async def _register_and_login(client: AsyncClient, username: str) -> str:
    await client.post(
        "/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )
    login = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-pw"}
    )
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin() -> dict:
    return {"X-API-Key": _VALID_KEY}


async def _seed_review(client: AsyncClient, db, slug: str, username: str, score: int = 4) -> int:
    """Create a movie + an author who rates it (through the API). Returns rating id."""
    await upsert_movie(db, _movie_data(slug))
    token = await _register_and_login(client, username)
    put = await client.put(
        f"/v1/movies/{slug}/rating",
        json={"score": score, "review_text": "seed review"},
        headers=_auth(token),
    )
    return put.json()["id"]


# ── POST /admin/reviews/{id}/hide — auth + 404 ───────────────────────────────


async def test_hide_review_without_key_returns_401(client):
    response = await client.post("/v1/admin/reviews/1/hide")
    assert response.status_code == 401


async def test_hide_unknown_review_returns_404(client):
    response = await client.post("/v1/admin/reviews/999999999/hide", headers=_admin())
    assert response.status_code == 404


async def test_unhide_unknown_review_returns_404(client):
    response = await client.post("/v1/admin/reviews/999999999/unhide", headers=_admin())
    assert response.status_code == 404


# ── Hide excludes from listings + aggregates ─────────────────────────────────


async def test_hide_review_excludes_from_item_ratings_and_aggregate(client, db):
    rating_id = await _seed_review(client, db, "mod-hide-movie-1", "mod-hide-author-1", score=4)

    # Before hiding: visible in the list and reflected in the aggregate.
    before_list = await client.get("/v1/movies/mod-hide-movie-1/ratings")
    assert before_list.json()["total"] == 1
    before_detail = await client.get("/v1/movies/mod-hide-movie-1")
    assert before_detail.json()["rating_internal"] == 4
    assert before_detail.json()["rating_count_internal"] == 1

    hide = await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())
    assert hide.status_code == 200
    assert hide.json() == {"id": rating_id, "is_hidden": True}

    # After hiding: gone from the list and no longer counted in the aggregate.
    after_list = await client.get("/v1/movies/mod-hide-movie-1/ratings")
    assert after_list.json()["total"] == 0
    after_detail = await client.get("/v1/movies/mod-hide-movie-1")
    assert after_detail.json()["rating_internal"] is None
    assert after_detail.json()["rating_count_internal"] == 0


async def test_hide_review_excludes_from_user_reviews(client, db):
    rating_id = await _seed_review(client, db, "mod-hide-movie-2", "mod-hide-author-2")

    before = await client.get("/v1/users/mod-hide-author-2/reviews")
    assert before.json()["total"] == 1

    await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())

    after = await client.get("/v1/users/mod-hide-author-2/reviews")
    assert after.status_code == 200
    assert after.json()["total"] == 0


async def test_hide_review_excludes_from_feed(client, db):
    # Feed entries key on their activity_events id (feature 54), not the
    # rating id, so identify the entry by its item slug instead.
    rating_id = await _seed_review(client, db, "mod-hide-movie-3", "mod-hide-author-3")
    viewer_token = await _register_and_login(client, "mod-hide-viewer-3")

    before = await client.get("/v1/feed?tab=popular", headers=_auth(viewer_token))
    assert any(item["item"]["slug"] == "mod-hide-movie-3" for item in before.json()["items"])

    await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())

    after = await client.get("/v1/feed?tab=popular", headers=_auth(viewer_token))
    assert all(item["item"]["slug"] != "mod-hide-movie-3" for item in after.json()["items"])


async def test_unhide_restores_review_and_aggregate(client, db):
    rating_id = await _seed_review(client, db, "mod-hide-movie-4", "mod-hide-author-4", score=5)

    await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())
    unhide = await client.post(f"/v1/admin/reviews/{rating_id}/unhide", headers=_admin())
    assert unhide.status_code == 200
    assert unhide.json() == {"id": rating_id, "is_hidden": False}

    listing = await client.get("/v1/movies/mod-hide-movie-4/ratings")
    assert listing.json()["total"] == 1
    detail = await client.get("/v1/movies/mod-hide-movie-4")
    assert detail.json()["rating_internal"] == 5
    assert detail.json()["rating_count_internal"] == 1


async def test_hide_is_idempotent(client, db):
    rating_id = await _seed_review(client, db, "mod-hide-movie-5", "mod-hide-author-5")

    first = await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())
    second = await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_hidden"] is True


# ── POST /admin/users/{username}/ban — auth + 404 ────────────────────────────


async def test_ban_user_without_key_returns_401(client):
    response = await client.post("/v1/admin/users/whoever/ban")
    assert response.status_code == 401


async def test_ban_unknown_user_returns_404(client):
    response = await client.post("/v1/admin/users/nobody-mod-ban/ban", headers=_admin())
    assert response.status_code == 404


async def test_unban_unknown_user_returns_404(client):
    response = await client.post("/v1/admin/users/nobody-mod-ban/unban", headers=_admin())
    assert response.status_code == 404


# ── Ban blocks login + refresh ───────────────────────────────────────────────


async def test_banned_user_cannot_login(client, db):
    await _register_and_login(client, "mod-ban-login-user")

    ban = await client.post("/v1/admin/users/mod-ban-login-user/ban", headers=_admin())
    assert ban.status_code == 200
    assert ban.json() == {"username": "mod-ban-login-user", "is_banned": True}

    login = await client.post(
        "/v1/auth/login", json={"username": "mod-ban-login-user", "password": "s3cret-pw"}
    )
    assert login.status_code == 401


async def test_banned_user_cannot_refresh(client, db):
    await client.post(
        "/v1/auth/register",
        json={
            "username": "mod-ban-refresh-user",
            "email": "mod-ban-refresh-user@example.com",
            "password": "s3cret-pw",
        },
    )
    login = await client.post(
        "/v1/auth/login", json={"username": "mod-ban-refresh-user", "password": "s3cret-pw"}
    )
    refresh_token = login.json()["refresh_token"]

    await client.post("/v1/admin/users/mod-ban-refresh-user/ban", headers=_admin())

    refresh = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 401


async def test_banned_user_access_token_revoked_immediately(client, db):
    """A ban must revoke an already-issued access token immediately (feature 58).

    Without this, a banned user keeps write access until the JWT expires
    (up to JWT_EXPIRE_MINUTES) since access tokens aren't looked up in the DB.
    """
    token = await _register_and_login(client, "mod-ban-immediate-user")

    # The token works before the ban.
    before = await client.get("/v1/users/me", headers=_auth(token))
    assert before.status_code == 200

    await client.post("/v1/admin/users/mod-ban-immediate-user/ban", headers=_admin())

    after = await client.get("/v1/users/me", headers=_auth(token))
    assert after.status_code == 401


async def test_unban_restores_login(client, db):
    await _register_and_login(client, "mod-unban-login-user")
    await client.post("/v1/admin/users/mod-unban-login-user/ban", headers=_admin())

    unban = await client.post("/v1/admin/users/mod-unban-login-user/unban", headers=_admin())
    assert unban.status_code == 200
    assert unban.json()["is_banned"] is False

    login = await client.post(
        "/v1/auth/login", json={"username": "mod-unban-login-user", "password": "s3cret-pw"}
    )
    assert login.status_code == 200


# ── Ban hides the user's reviews from listings + aggregates ──────────────────


async def test_ban_hides_user_reviews_from_all_surfaces(client, db):
    await _seed_review(client, db, "mod-ban-movie-1", "mod-ban-author-1", score=4)

    await client.post("/v1/admin/users/mod-ban-author-1/ban", headers=_admin())

    ratings = await client.get("/v1/movies/mod-ban-movie-1/ratings")
    assert ratings.json()["total"] == 0

    reviews = await client.get("/v1/users/mod-ban-author-1/reviews")
    assert reviews.status_code == 200
    assert reviews.json()["total"] == 0

    detail = await client.get("/v1/movies/mod-ban-movie-1")
    assert detail.json()["rating_internal"] is None
    assert detail.json()["rating_count_internal"] == 0

    viewer_token = await _register_and_login(client, "mod-ban-viewer-1")
    feed = await client.get("/v1/feed?tab=popular", headers=_auth(viewer_token))
    # Feed entries key on their activity_events id (feature 54), not the
    # rating id, so identify the entry by its item slug instead.
    assert all(item["item"]["slug"] != "mod-ban-movie-1" for item in feed.json()["items"])


async def test_unban_restores_user_reviews_and_aggregate(client, db):
    await _seed_review(client, db, "mod-ban-movie-2", "mod-ban-author-2", score=3)

    await client.post("/v1/admin/users/mod-ban-author-2/ban", headers=_admin())
    await client.post("/v1/admin/users/mod-ban-author-2/unban", headers=_admin())

    ratings = await client.get("/v1/movies/mod-ban-movie-2/ratings")
    assert ratings.json()["total"] == 1
    detail = await client.get("/v1/movies/mod-ban-movie-2")
    assert detail.json()["rating_internal"] == 3
    assert detail.json()["rating_count_internal"] == 1


async def test_ban_is_idempotent(client, db):
    await _register_and_login(client, "mod-ban-idem-user")

    first = await client.post("/v1/admin/users/mod-ban-idem-user/ban", headers=_admin())
    second = await client.post("/v1/admin/users/mod-ban-idem-user/ban", headers=_admin())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["is_banned"] is True
