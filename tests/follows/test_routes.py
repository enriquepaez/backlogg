"""Endpoint tests for the follows feature.

Covers:
- POST/DELETE /users/{username}/follow (auth, idempotent, self-follow 422, 404).
- GET /users/{username}/followers, /following (public, paginated).
- GET /users/{username} extended with follower_count/following_count.
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


async def _register(client: AsyncClient, username: str) -> None:
    await client.post(
        "/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── POST /users/{username}/follow ────────────────────────────────────────


async def test_follow_without_token_returns_401(client):
    await _register(client, "route-follow-target-1")
    response = await client.post("/v1/users/route-follow-target-1/follow")
    assert response.status_code == 401


async def test_follow_returns_204_and_updates_counts(client):
    token = await _register_and_login(client, "route-follow-user-1")
    await _register(client, "route-follow-target-2")

    response = await client.post(
        "/v1/users/route-follow-target-2/follow", headers=_auth_headers(token)
    )
    assert response.status_code == 204

    profile = await client.get("/v1/users/route-follow-target-2")
    assert profile.status_code == 200
    assert profile.json()["follower_count"] == 1

    own = await client.get("/v1/users/route-follow-user-1")
    assert own.json()["following_count"] == 1


async def test_follow_twice_is_idempotent(client):
    token = await _register_and_login(client, "route-follow-user-2")
    await _register(client, "route-follow-target-3")

    first = await client.post(
        "/v1/users/route-follow-target-3/follow", headers=_auth_headers(token)
    )
    second = await client.post(
        "/v1/users/route-follow-target-3/follow", headers=_auth_headers(token)
    )
    assert first.status_code == 204
    assert second.status_code == 204

    profile = await client.get("/v1/users/route-follow-target-3")
    assert profile.json()["follower_count"] == 1


async def test_follow_self_returns_422(client):
    token = await _register_and_login(client, "route-follow-self")
    response = await client.post("/v1/users/route-follow-self/follow", headers=_auth_headers(token))
    assert response.status_code == 422


async def test_follow_unknown_username_returns_404(client):
    token = await _register_and_login(client, "route-follow-user-3")
    response = await client.post(
        "/v1/users/nobody-has-this-username-route/follow", headers=_auth_headers(token)
    )
    assert response.status_code == 404


# ── DELETE /users/{username}/follow ──────────────────────────────────────


async def test_unfollow_without_token_returns_401(client):
    await _register(client, "route-unfollow-target-1")
    response = await client.delete("/v1/users/route-unfollow-target-1/follow")
    assert response.status_code == 401


async def test_unfollow_removes_relationship(client):
    token = await _register_and_login(client, "route-unfollow-user-1")
    await _register(client, "route-unfollow-target-2")

    await client.post("/v1/users/route-unfollow-target-2/follow", headers=_auth_headers(token))
    response = await client.delete(
        "/v1/users/route-unfollow-target-2/follow", headers=_auth_headers(token)
    )
    assert response.status_code == 204

    profile = await client.get("/v1/users/route-unfollow-target-2")
    assert profile.json()["follower_count"] == 0


async def test_unfollow_tolerant_when_not_following(client):
    token = await _register_and_login(client, "route-unfollow-user-2")
    await _register(client, "route-unfollow-target-3")

    # Never followed — unfollowing must not fail.
    response = await client.delete(
        "/v1/users/route-unfollow-target-3/follow", headers=_auth_headers(token)
    )
    assert response.status_code == 204


# ── GET /users/{username}/followers, /following ──────────────────────────


async def test_list_followers_public_paginated(client):
    await _register(client, "route-list-target")
    token1 = await _register_and_login(client, "route-list-f1")
    token2 = await _register_and_login(client, "route-list-f2")

    await client.post("/v1/users/route-list-target/follow", headers=_auth_headers(token1))
    await client.post("/v1/users/route-list-target/follow", headers=_auth_headers(token2))

    response = await client.get("/v1/users/route-list-target/followers?page=1&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert "username" in body["items"][0]


async def test_list_following_public_paginated(client):
    token = await _register_and_login(client, "route-list-following-src")
    await _register(client, "route-list-following-t1")
    await _register(client, "route-list-following-t2")

    await client.post("/v1/users/route-list-following-t1/follow", headers=_auth_headers(token))
    await client.post("/v1/users/route-list-following-t2/follow", headers=_auth_headers(token))

    response = await client.get("/v1/users/route-list-following-src/following")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    usernames = {item["username"] for item in body["items"]}
    assert usernames == {"route-list-following-t1", "route-list-following-t2"}


async def test_list_followers_unknown_username_returns_404(client):
    response = await client.get("/v1/users/nobody-has-this-username-followers-route/followers")
    assert response.status_code == 404


async def test_list_following_unknown_username_returns_404(client):
    response = await client.get("/v1/users/nobody-has-this-username-following-route/following")
    assert response.status_code == 404


# ── GET /users/{username} extension ──────────────────────────────────────


async def test_public_profile_includes_follow_counts_default_zero(client):
    await _register(client, "route-profile-counts")
    response = await client.get("/v1/users/route-profile-counts")
    assert response.status_code == 200
    body = response.json()
    assert body["follower_count"] == 0
    assert body["following_count"] == 0
    assert "email" not in body
