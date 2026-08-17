"""Endpoint tests for /auth/register, /auth/login, /users/me, /users/{username}."""

from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.core.config import settings
from backlogg.main import app
from backlogg.users import service


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
        "/v1/auth/register", json=_register_payload("route-user-1", "route-user-1@example.com")
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "route-user-1"
    assert body["email"] == "route-user-1@example.com"
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_duplicate_username_returns_409(client):
    await client.post(
        "/v1/auth/register",
        json=_register_payload("route-user-dup", "route-user-dup-a@example.com"),
    )
    response = await client.post(
        "/v1/auth/register",
        json=_register_payload("route-user-dup", "route-user-dup-b@example.com"),
    )
    assert response.status_code == 409


async def test_register_duplicate_email_returns_409(client):
    await client.post(
        "/v1/auth/register",
        json=_register_payload("route-user-dup-email-a", "route-dup-email@example.com"),
    )
    response = await client.post(
        "/v1/auth/register",
        json=_register_payload("route-user-dup-email-b", "route-dup-email@example.com"),
    )
    assert response.status_code == 409


# ── POST /auth/login ─────────────────────────────────────────────────────────


async def test_login_returns_200_with_token(client):
    await client.post(
        "/v1/auth/register", json=_register_payload("route-login-user", "route-login@example.com")
    )
    response = await client.post(
        "/v1/auth/login", json={"username": "route-login-user", "password": "s3cret-password"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_invalid_credentials_returns_401(client):
    await client.post(
        "/v1/auth/register",
        json=_register_payload("route-login-user-2", "route-login-2@example.com"),
    )
    response = await client.post(
        "/v1/auth/login", json={"username": "route-login-user-2", "password": "wrong-password"}
    )
    assert response.status_code == 401


async def test_login_unknown_username_returns_401(client):
    response = await client.post(
        "/v1/auth/login", json={"username": "nobody-registered-this-user", "password": "whatever"}
    )
    assert response.status_code == 401


# ── GET /users/me ────────────────────────────────────────────────────────────


async def test_get_me_without_token_returns_401(client):
    response = await client.get("/v1/users/me")
    assert response.status_code == 401


async def test_get_me_with_valid_token_returns_200(client):
    await client.post(
        "/v1/auth/register", json=_register_payload("route-me-user", "route-me@example.com")
    )
    login_response = await client.post(
        "/v1/auth/login", json={"username": "route-me-user", "password": "s3cret-password"}
    )
    token = login_response.json()["access_token"]

    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "route-me-user"
    assert body["email"] == "route-me@example.com"
    assert body["is_admin"] is False


async def test_get_me_with_invalid_token_returns_401(client):
    response = await client.get(
        "/v1/users/me", headers={"Authorization": "Bearer not-a-valid-token"}
    )
    assert response.status_code == 401


# ── PATCH /users/me ──────────────────────────────────────────────────────────


async def test_patch_me_without_token_returns_401(client):
    response = await client.patch("/v1/users/me", json={"display_name": "New Name"})
    assert response.status_code == 401


async def test_patch_me_updates_profile(client):
    await client.post(
        "/v1/auth/register", json=_register_payload("route-patch-user", "route-patch@example.com")
    )
    login_response = await client.post(
        "/v1/auth/login", json={"username": "route-patch-user", "password": "s3cret-password"}
    )
    token = login_response.json()["access_token"]

    response = await client.patch(
        "/v1/users/me",
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
        "/v1/auth/register", json=_register_payload("route-public-user", "route-public@example.com")
    )
    response = await client.get("/v1/users/route-public-user")
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "route-public-user"
    assert "email" not in body


async def test_get_user_public_profile_returns_404(client):
    response = await client.get("/v1/users/nobody-has-this-username-ever")
    assert response.status_code == 404


# ── POST/DELETE /users/me/avatar (feature 51) ───────────────────────────────


def _configure_r2(monkeypatch) -> None:
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://avatars.example.com")


async def _register_and_login(client, username: str, email: str) -> str:
    await client.post("/v1/auth/register", json=_register_payload(username, email))
    login_response = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-password"}
    )
    return login_response.json()["access_token"]


async def test_upload_avatar_without_token_returns_401(client):
    response = await client.post(
        "/v1/users/me/avatar",
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
    )
    assert response.status_code == 401


async def test_upload_avatar_invalid_type_returns_422(client, monkeypatch):
    _configure_r2(monkeypatch)
    token = await _register_and_login(client, "route-avatar-bad-type", "route-avatar-1@example.com")

    response = await client.post(
        "/v1/users/me/avatar",
        files={"file": ("notes.txt", b"just text", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


async def test_upload_avatar_too_large_returns_413(client, monkeypatch):
    _configure_r2(monkeypatch)
    token = await _register_and_login(client, "route-avatar-too-big", "route-avatar-2@example.com")
    oversized = b"x" * (service._MAX_AVATAR_SIZE_BYTES + 1)

    response = await client.post(
        "/v1/users/me/avatar",
        files={"file": ("avatar.png", oversized, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 413


async def test_upload_avatar_missing_credentials_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    token = await _register_and_login(client, "route-avatar-no-creds", "route-avatar-3@example.com")

    response = await client.post(
        "/v1/users/me/avatar",
        files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503


async def test_upload_avatar_success_returns_200(client, monkeypatch):
    _configure_r2(monkeypatch)
    token = await _register_and_login(client, "route-avatar-success", "route-avatar-4@example.com")
    fake_url = "https://avatars.example.com/avatars/1/fake-uuid.png"

    with patch.object(service._r2, "upload", new_callable=AsyncMock, return_value=fake_url):
        response = await client.post(
            "/v1/users/me/avatar",
            files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"] == fake_url
    assert body["username"] == "route-avatar-success"


async def test_delete_avatar_without_token_returns_401(client):
    response = await client.delete("/v1/users/me/avatar")
    assert response.status_code == 401


async def test_delete_avatar_success_returns_204(client, monkeypatch):
    _configure_r2(monkeypatch)
    token = await _register_and_login(client, "route-avatar-delete", "route-avatar-5@example.com")
    fake_url = "https://avatars.example.com/avatars/1/fake-uuid.png"

    with patch.object(service._r2, "upload", new_callable=AsyncMock, return_value=fake_url):
        await client.post(
            "/v1/users/me/avatar",
            files={"file": ("avatar.png", b"fake-png-bytes", "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )

    with patch.object(service._r2, "delete", new_callable=AsyncMock) as mock_delete:
        response = await client.delete(
            "/v1/users/me/avatar", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 204
    mock_delete.assert_called_once()

    me_response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.json()["avatar_url"] is None


async def test_delete_avatar_already_null_returns_204(client, monkeypatch):
    _configure_r2(monkeypatch)
    token = await _register_and_login(
        client, "route-avatar-delete-noop", "route-avatar-6@example.com"
    )

    with patch.object(service._r2, "delete", new_callable=AsyncMock) as mock_delete:
        response = await client.delete(
            "/v1/users/me/avatar", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 204
    mock_delete.assert_not_called()
