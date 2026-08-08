"""Tests for refresh-token rotation, revocation, reuse detection and expiry.

Covers both the service layer (backlogg/users/service.py) against the real
test DB and the HTTP endpoints (/auth/login, /auth/refresh, /auth/logout)
through httpx.AsyncClient, matching the rest of the suite.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.users import repository as repo
from backlogg.users import service
from backlogg.users.auth import hash_refresh_token
from backlogg.users.schemas import LogoutRequest, RefreshRequest, UserCreate, UserLogin

# ── Service-layer tests ───────────────────────────────────────────────────────


async def _register_and_login(db, username: str) -> tuple:
    await service.register_user(
        db,
        UserCreate(
            username=username,
            email=f"{username}@example.com",
            password="s3cret-password",
        ),
    )
    pair = await service.login_user(db, UserLogin(username=username, password="s3cret-password"))
    user = await repo.get_user_by_username(db, username)
    return user, pair


async def test_login_persists_only_the_refresh_hash(db):
    _, pair = await _register_and_login(db, "rt-login-user")
    assert pair.access_token
    assert pair.refresh_token
    assert pair.token_type == "bearer"

    stored = await repo.get_refresh_token_by_hash(db, hash_refresh_token(pair.refresh_token))
    assert stored is not None
    assert stored.token_hash != pair.refresh_token
    assert stored.revoked_at is None


async def test_refresh_rotates_pair_and_revokes_old(db):
    _, pair = await _register_and_login(db, "rt-rotate-user")

    new_pair = await service.refresh_tokens(db, RefreshRequest(refresh_token=pair.refresh_token))
    assert new_pair.refresh_token != pair.refresh_token
    assert new_pair.access_token

    old = await repo.get_refresh_token_by_hash(db, hash_refresh_token(pair.refresh_token))
    new = await repo.get_refresh_token_by_hash(db, hash_refresh_token(new_pair.refresh_token))
    assert old.revoked_at is not None
    assert new.revoked_at is None


async def test_logout_revokes_and_is_idempotent(db):
    user, pair = await _register_and_login(db, "rt-logout-user")

    await service.logout_user(db, user, LogoutRequest(refresh_token=pair.refresh_token))
    stored = await repo.get_refresh_token_by_hash(db, hash_refresh_token(pair.refresh_token))
    assert stored.revoked_at is not None
    first_revoked_at = stored.revoked_at

    # Revoking a second time must not fail and must not move the timestamp.
    await service.logout_user(db, user, LogoutRequest(refresh_token=pair.refresh_token))
    stored = await repo.get_refresh_token_by_hash(db, hash_refresh_token(pair.refresh_token))
    assert stored.revoked_at == first_revoked_at


async def test_reuse_of_revoked_refresh_401_and_revokes_chain(db):
    user, pair = await _register_and_login(db, "rt-reuse-user")

    # Legit rotation: rt1 -> rt2.
    pair2 = await service.refresh_tokens(db, RefreshRequest(refresh_token=pair.refresh_token))

    # Reusing rt1 (now revoked) is detected.
    with pytest.raises(HTTPException) as exc_info:
        await service.refresh_tokens(db, RefreshRequest(refresh_token=pair.refresh_token))
    assert exc_info.value.status_code == 401

    # Defense: every active token for the user is revoked, including rt2.
    rt2 = await repo.get_refresh_token_by_hash(db, hash_refresh_token(pair2.refresh_token))
    assert rt2.revoked_at is not None


async def test_expired_refresh_returns_401(db):
    await service.register_user(
        db,
        UserCreate(
            username="rt-expired-user",
            email="rt-expired-user@example.com",
            password="s3cret-password",
        ),
    )
    user = await repo.get_user_by_username(db, "rt-expired-user")

    plaintext = "expired-opaque-token-value"
    past = datetime.now(UTC) - timedelta(days=1)
    await repo.create_refresh_token(db, user.id, hash_refresh_token(plaintext), past)

    with pytest.raises(HTTPException) as exc_info:
        await service.refresh_tokens(db, RefreshRequest(refresh_token=plaintext))
    assert exc_info.value.status_code == 401


async def test_unknown_refresh_returns_401(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.refresh_tokens(db, RefreshRequest(refresh_token="never-issued-this"))
    assert exc_info.value.status_code == 401


# ── Endpoint tests ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_login_http(client, username: str) -> dict:
    await client.post(
        "/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "s3cret-password",
        },
    )
    response = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-password"}
    )
    return response.json()


async def test_login_returns_token_pair(client):
    body = await _register_and_login_http(client, "rt-http-login")
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_refresh_endpoint_rotates(client):
    pair = await _register_and_login_http(client, "rt-http-refresh")
    response = await client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 200
    new_pair = response.json()
    assert new_pair["refresh_token"] != pair["refresh_token"]
    assert new_pair["access_token"]


async def test_refresh_endpoint_reuse_returns_401(client):
    pair = await _register_and_login_http(client, "rt-http-reuse")
    # First rotation succeeds.
    await client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    # Reusing the now-revoked token fails.
    response = await client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 401


async def test_logout_endpoint_requires_auth(client):
    pair = await _register_and_login_http(client, "rt-http-logout-noauth")
    response = await client.post("/v1/auth/logout", json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 401


async def test_logout_endpoint_revokes_and_is_idempotent(client):
    pair = await _register_and_login_http(client, "rt-http-logout")
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    first = await client.post(
        "/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}, headers=headers
    )
    assert first.status_code == 204

    # Idempotent: logging out again succeeds.
    second = await client.post(
        "/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}, headers=headers
    )
    assert second.status_code == 204

    # The revoked refresh can no longer be rotated.
    refresh = await client.post("/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert refresh.status_code == 401
