"""Endpoint tests for the notifications feature.

Covers:
- GET /notifications (auth required, paginated, reverse-chrono, actor info).
- GET /notifications/unread_count (auth).
- POST /notifications/read (auth, marks all or specific ids, idempotent).
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app


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
