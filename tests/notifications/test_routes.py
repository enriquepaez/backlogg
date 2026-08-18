"""Endpoint tests for the notifications feature.

Covers:
- GET /notifications (auth required, paginated, reverse-chrono, actor info).
- GET /notifications/unread_count (auth).
- POST /notifications/read (auth, marks all or specific ids, idempotent).
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as movies_repo


def _movie_data(slug: str) -> dict:
    return {
        "title": "Route Notif Movie",
        "original_title": "Route Notif Movie",
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


# ── auth ──────────────────────────────────────────────────────────────────


async def test_list_notifications_without_token_returns_401(client):
    response = await client.get("/v1/notifications")
    assert response.status_code == 401


async def test_unread_count_without_token_returns_401(client):
    response = await client.get("/v1/notifications/unread_count")
    assert response.status_code == 401


async def test_mark_read_without_token_returns_401(client):
    response = await client.post("/v1/notifications/read")
    assert response.status_code == 401


async def test_delete_notification_without_token_returns_401(client):
    response = await client.delete("/v1/notifications/1")
    assert response.status_code == 401


# ── GET /notifications + unread_count ─────────────────────────────────────


async def test_list_notifications_after_follow(client):
    actor_token = await _register_and_login(client, "route-notif-actor-1")
    target_token = await _register_and_login(client, "route-notif-target-1")

    await client.post("/v1/users/route-notif-target-1/follow", headers=_auth_headers(actor_token))

    response = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["type"] == "new_follower"
    assert entry["is_read"] is False
    assert entry["actor"]["username"] == "route-notif-actor-1"
    assert "target" in entry


async def test_unread_count_reflects_notifications(client):
    actor_token = await _register_and_login(client, "route-notif-actor-2")
    target_token = await _register_and_login(client, "route-notif-target-2")

    resp0 = await client.get("/v1/notifications/unread_count", headers=_auth_headers(target_token))
    assert resp0.json()["unread_count"] == 0

    await client.post("/v1/users/route-notif-target-2/follow", headers=_auth_headers(actor_token))

    resp1 = await client.get("/v1/notifications/unread_count", headers=_auth_headers(target_token))
    assert resp1.json()["unread_count"] == 1


# ── POST /notifications/read ──────────────────────────────────────────────


async def test_mark_all_read_and_idempotent(client):
    actor_token = await _register_and_login(client, "route-notif-actor-3")
    target_token = await _register_and_login(client, "route-notif-target-3")
    await client.post("/v1/users/route-notif-target-3/follow", headers=_auth_headers(actor_token))

    first = await client.post("/v1/notifications/read", headers=_auth_headers(target_token))
    assert first.status_code == 204

    resp = await client.get("/v1/notifications/unread_count", headers=_auth_headers(target_token))
    assert resp.json()["unread_count"] == 0

    # Idempotent — marking again is still 204 and count stays 0.
    second = await client.post("/v1/notifications/read", headers=_auth_headers(target_token))
    assert second.status_code == 204
    resp2 = await client.get("/v1/notifications/unread_count", headers=_auth_headers(target_token))
    assert resp2.json()["unread_count"] == 0


async def test_mark_read_specific_ids(client):
    actor1_token = await _register_and_login(client, "route-notif-actor-4a")
    actor2_token = await _register_and_login(client, "route-notif-actor-4b")
    target_token = await _register_and_login(client, "route-notif-target-4")

    await client.post("/v1/users/route-notif-target-4/follow", headers=_auth_headers(actor1_token))
    await client.post("/v1/users/route-notif-target-4/follow", headers=_auth_headers(actor2_token))

    listing = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    first_id = listing.json()["items"][0]["id"]

    marked = await client.post(
        "/v1/notifications/read",
        json={"ids": [first_id]},
        headers=_auth_headers(target_token),
    )
    assert marked.status_code == 204

    resp = await client.get("/v1/notifications/unread_count", headers=_auth_headers(target_token))
    assert resp.json()["unread_count"] == 1


# ── target resolution (item_type/slug) ────────────────────────────────────


async def test_new_follower_target_fields_are_null(client):
    actor_token = await _register_and_login(client, "route-notif-actor-5")
    target_token = await _register_and_login(client, "route-notif-target-5")

    await client.post("/v1/users/route-notif-target-5/follow", headers=_auth_headers(actor_token))

    response = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    target = response.json()["items"][0]["target"]
    assert target["target_type"] is None
    assert target["target_id"] is None
    assert target["item_type"] is None
    assert target["slug"] is None


async def test_review_like_target_resolves_item_type_and_slug(client, db):
    author_token = await _register_and_login(client, "route-notif-author-1")
    liker_token = await _register_and_login(client, "route-notif-liker-1")
    await movies_repo.upsert_movie(db, _movie_data("route-notif-movie-1"))

    rating_resp = await client.put(
        "/v1/movies/route-notif-movie-1/rating",
        json={"score": 5, "review_text": "Masterpiece"},
        headers=_auth_headers(author_token),
    )
    rating_id = rating_resp.json()["id"]

    await client.post(f"/v1/ratings/{rating_id}/like", headers=_auth_headers(liker_token))

    response = await client.get("/v1/notifications", headers=_auth_headers(author_token))
    body = response.json()
    entry = body["items"][0]
    assert entry["type"] == "review_like"
    target = entry["target"]
    assert target["target_type"] == "review"
    assert target["target_id"] == rating_id
    assert target["item_type"] == "MOVIE"
    assert target["slug"] == "route-notif-movie-1"


async def test_user_completed_target_resolves_item_type_and_slug(client, db):
    follower_token = await _register_and_login(client, "route-notif-follower-1")
    completer_token = await _register_and_login(client, "route-notif-completer-1")
    await movies_repo.upsert_movie(db, _movie_data("route-notif-movie-2"))

    await client.post(
        "/v1/users/route-notif-completer-1/follow", headers=_auth_headers(follower_token)
    )
    await client.put(
        "/v1/movies/route-notif-movie-2/library",
        json={"status": "completed"},
        headers=_auth_headers(completer_token),
    )

    response = await client.get("/v1/notifications", headers=_auth_headers(follower_token))
    body = response.json()
    entry = body["items"][0]
    assert entry["type"] == "user_completed"
    assert entry["actor"]["username"] == "route-notif-completer-1"
    target = entry["target"]
    assert target["target_type"] == "MOVIE"
    assert target["item_type"] == "MOVIE"
    assert target["slug"] == "route-notif-movie-2"


# ── DELETE /notifications/{id} ────────────────────────────────────────────


async def test_delete_own_notification_returns_204_and_removes_it(client):
    actor_token = await _register_and_login(client, "route-notif-actor-6")
    target_token = await _register_and_login(client, "route-notif-target-6")
    await client.post("/v1/users/route-notif-target-6/follow", headers=_auth_headers(actor_token))

    listing = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    notification_id = listing.json()["items"][0]["id"]

    delete_resp = await client.delete(
        f"/v1/notifications/{notification_id}", headers=_auth_headers(target_token)
    )
    assert delete_resp.status_code == 204

    after = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    assert after.json()["total"] == 0


async def test_delete_another_users_notification_returns_404_and_keeps_it(client):
    actor_token = await _register_and_login(client, "route-notif-actor-7")
    target_token = await _register_and_login(client, "route-notif-target-7")
    other_token = await _register_and_login(client, "route-notif-other-7")
    await client.post("/v1/users/route-notif-target-7/follow", headers=_auth_headers(actor_token))

    listing = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    notification_id = listing.json()["items"][0]["id"]

    delete_resp = await client.delete(
        f"/v1/notifications/{notification_id}", headers=_auth_headers(other_token)
    )
    assert delete_resp.status_code == 404

    after = await client.get("/v1/notifications", headers=_auth_headers(target_token))
    assert after.json()["total"] == 1


async def test_delete_nonexistent_notification_returns_404(client):
    token = await _register_and_login(client, "route-notif-nonexistent-8")

    response = await client.delete("/v1/notifications/999999999", headers=_auth_headers(token))
    assert response.status_code == 404
