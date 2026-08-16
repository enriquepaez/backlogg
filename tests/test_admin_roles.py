"""Endpoint tests for admin role management (feature 47 — admin_role_management).

Covers:
- POST /v1/admin/users/{username}/grant-admin + /revoke-admin: require both
  X-API-Key and a valid Bearer token for a superadmin caller.
- 403 for a caller authenticated but not is_superadmin (even with X-API-Key).
- 401 without a valid Bearer token (X-API-Key alone is not enough).
- Idempotency (grant to an already-admin user, revoke from a non-admin one).
- 404 for an unknown target username.
- GET /v1/users/me for the affected user reflects the change after the flip.

There is no API to set ``is_superadmin`` (by design, DB-only) — tests flip it
directly on the fetched ORM user through the shared test ``db`` session before
issuing the request, which is the only way to exercise these endpoints.
"""

from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.users import repository as users_repo

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


def _admin_auth(token: str) -> dict:
    return {**_admin(), **_auth(token)}


async def _make_superadmin(db, username: str) -> None:
    """Flip is_superadmin=True directly through the shared test DB session."""
    user = await users_repo.get_user_by_username(db, username)
    user.is_superadmin = True
    await db.flush()


# ── Auth gates ────────────────────────────────────────────────────────────────


async def test_grant_admin_without_api_key_returns_401(client):
    response = await client.post("/v1/admin/users/whoever/grant-admin")
    assert response.status_code == 401


async def test_grant_admin_without_bearer_token_returns_401(client):
    response = await client.post("/v1/admin/users/whoever/grant-admin", headers=_admin())
    assert response.status_code == 401


async def test_grant_admin_by_non_superadmin_returns_403(client, db):
    caller_token = await _register_and_login(client, "role-plain-caller")
    await _register_and_login(client, "role-target-1")

    response = await client.post(
        "/v1/admin/users/role-target-1/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 403


async def test_grant_admin_by_admin_not_superadmin_returns_403(client, db):
    """is_admin alone is not enough — the caller must be is_superadmin."""
    caller_token = await _register_and_login(client, "role-admin-caller")
    caller = await users_repo.get_user_by_username(db, "role-admin-caller")
    await users_repo.set_user_admin(db, caller, True)
    await _register_and_login(client, "role-target-2")

    response = await client.post(
        "/v1/admin/users/role-target-2/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 403


# ── Happy path: grant / revoke by a superadmin ───────────────────────────────


async def test_grant_admin_by_superadmin_returns_200(client, db):
    caller_token = await _register_and_login(client, "role-super-1")
    await _make_superadmin(db, "role-super-1")
    await _register_and_login(client, "role-target-3")

    response = await client.post(
        "/v1/admin/users/role-target-3/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200
    assert response.json() == {"username": "role-target-3", "is_admin": True}


async def test_revoke_admin_by_superadmin_returns_200(client, db):
    caller_token = await _register_and_login(client, "role-super-2")
    await _make_superadmin(db, "role-super-2")
    await _register_and_login(client, "role-target-4")
    target = await users_repo.get_user_by_username(db, "role-target-4")
    await users_repo.set_user_admin(db, target, True)

    response = await client.post(
        "/v1/admin/users/role-target-4/revoke-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200
    assert response.json() == {"username": "role-target-4", "is_admin": False}


# ── Idempotency ───────────────────────────────────────────────────────────────


async def test_grant_admin_is_idempotent(client, db):
    caller_token = await _register_and_login(client, "role-super-3")
    await _make_superadmin(db, "role-super-3")
    await _register_and_login(client, "role-target-5")
    target = await users_repo.get_user_by_username(db, "role-target-5")
    await users_repo.set_user_admin(db, target, True)

    response = await client.post(
        "/v1/admin/users/role-target-5/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200
    assert response.json() == {"username": "role-target-5", "is_admin": True}


async def test_revoke_admin_is_idempotent(client, db):
    caller_token = await _register_and_login(client, "role-super-4")
    await _make_superadmin(db, "role-super-4")
    await _register_and_login(client, "role-target-6")

    response = await client.post(
        "/v1/admin/users/role-target-6/revoke-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200
    assert response.json() == {"username": "role-target-6", "is_admin": False}


# ── 404 ───────────────────────────────────────────────────────────────────────


async def test_grant_admin_unknown_user_returns_404(client, db):
    caller_token = await _register_and_login(client, "role-super-5")
    await _make_superadmin(db, "role-super-5")

    response = await client.post(
        "/v1/admin/users/role-nobody/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 404


async def test_revoke_admin_unknown_user_returns_404(client, db):
    caller_token = await _register_and_login(client, "role-super-6")
    await _make_superadmin(db, "role-super-6")

    response = await client.post(
        "/v1/admin/users/role-nobody/revoke-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 404


# ── UserMeOut reflects the change ────────────────────────────────────────────


async def test_grant_admin_reflected_in_users_me(client, db):
    caller_token = await _register_and_login(client, "role-super-7")
    await _make_superadmin(db, "role-super-7")
    target_token = await _register_and_login(client, "role-target-7")

    before = await client.get("/v1/users/me", headers=_auth(target_token))
    assert before.json()["is_admin"] is False

    await client.post(
        "/v1/admin/users/role-target-7/grant-admin", headers=_admin_auth(caller_token)
    )

    after = await client.get("/v1/users/me", headers=_auth(target_token))
    assert after.json()["is_admin"] is True


async def test_revoke_admin_reflected_in_users_me(client, db):
    caller_token = await _register_and_login(client, "role-super-8")
    await _make_superadmin(db, "role-super-8")
    target_token = await _register_and_login(client, "role-target-8")
    target = await users_repo.get_user_by_username(db, "role-target-8")
    await users_repo.set_user_admin(db, target, True)

    await client.post(
        "/v1/admin/users/role-target-8/revoke-admin", headers=_admin_auth(caller_token)
    )

    after = await client.get("/v1/users/me", headers=_auth(target_token))
    assert after.json()["is_admin"] is False


# ── is_superadmin exposure ────────────────────────────────────────────────────


async def test_users_me_exposes_is_superadmin(client, db):
    token = await _register_and_login(client, "role-super-9")
    await _make_superadmin(db, "role-super-9")

    response = await client.get("/v1/users/me", headers=_auth(token))
    assert response.json()["is_superadmin"] is True


async def test_public_profile_never_exposes_is_superadmin(client, db):
    token = await _register_and_login(client, "role-super-10")
    await _make_superadmin(db, "role-super-10")
    assert token  # caller identity established via db flip, not the token

    response = await client.get("/v1/users/role-super-10")
    assert "is_superadmin" not in response.json()
    assert "is_admin" not in response.json()
