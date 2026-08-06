"""Endpoint tests for /auth/register, /auth/login, /users/me, /users/{username}."""

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


def _register_payload(username: str, email: str, password: str = "s3cret-password") -> dict:
    return {"username": username, "email": email, "password": password}


# ── POST /auth/register ─────────────────────────────────────────────────────


async def test_register_returns_201(client):
    response = await client.post(
        "/auth/register", json=_register_payload("route-user-1", "route-user-1@example.com")
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "route-user-1"
    assert body["email"] == "route-user-1@example.com"
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_duplicate_username_returns_409(client):
    await client.post(
        "/auth/register", json=_register_payload("route-user-dup", "route-user-dup-a@example.com")
    )
    response = await client.post(
        "/auth/register", json=_register_payload("route-user-dup", "route-user-dup-b@example.com")
    )
    assert response.status_code == 409


async def test_register_duplicate_email_returns_409(client):
    await client.post(
        "/auth/register",
        json=_register_payload("route-user-dup-email-a", "route-dup-email@example.com"),
    )
    response = await client.post(
        "/auth/register",
        json=_register_payload("route-user-dup-email-b", "route-dup-email@example.com"),
    )
    assert response.status_code == 409


# ── POST /auth/login ─────────────────────────────────────────────────────────


async def test_login_returns_200_with_token(client):
    await client.post(
        "/auth/register", json=_register_payload("route-login-user", "route-login@example.com")
    )
    response = await client.post(
        "/auth/login", json={"username": "route-login-user", "password": "s3cret-password"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_invalid_credentials_returns_401(client):
    await client.post(
        "/auth/register",
        json=_register_payload("route-login-user-2", "route-login-2@example.com"),
    )
    response = await client.post(
        "/auth/login", json={"username": "route-login-user-2", "password": "wrong-password"}
    )
    assert response.status_code == 401


async def test_login_unknown_username_returns_401(client):
    response = await client.post(
        "/auth/login", json={"username": "nobody-registered-this-user", "password": "whatever"}
    )
    assert response.status_code == 401


# ── GET /users/me ────────────────────────────────────────────────────────────


async def test_get_me_without_token_returns_401(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_get_me_with_valid_token_returns_200(client):
    await client.post(
        "/auth/register", json=_register_payload("route-me-user", "route-me@example.com")
    )
    login_response = await client.post(
        "/auth/login", json={"username": "route-me-user", "password": "s3cret-password"}
    )
    token = login_response.json()["access_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "route-me-user"
    assert body["email"] == "route-me@example.com"


async def test_get_me_with_invalid_token_returns_401(client):
    response = await client.get("/users/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert response.status_code == 401


# ── PATCH /users/me ──────────────────────────────────────────────────────────


async def test_patch_me_without_token_returns_401(client):
    response = await client.patch("/users/me", json={"display_name": "New Name"})
    assert response.status_code == 401


async def test_patch_me_updates_profile(client):
    await client.post(
        "/auth/register", json=_register_payload("route-patch-user", "route-patch@example.com")
    )
    login_response = await client.post(
        "/auth/login", json={"username": "route-patch-user", "password": "s3cret-password"}
    )
    token = login_response.json()["access_token"]

    response = await client.patch(
        "/users/me",
        json={"display_name": "Patched Name", "bio": "Patched bio"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Patched Name"
    assert body["bio"] == "Patched bio"


# ── GET /users/{username} ───────────────────────────────────────────────────


async def test_get_user_public_profile_returns_200_without_email(client):
    await client.post(
        "/auth/register", json=_register_payload("route-public-user", "route-public@example.com")
    )
    response = await client.get("/users/route-public-user")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "route-public-user"
    assert "email" not in body


async def test_get_user_public_profile_returns_404(client):
    response = await client.get("/users/nobody-has-this-username-ever")
    assert response.status_code == 404
