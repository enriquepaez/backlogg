"""Tests for GET /admin/users (feature 48 — admin_users_list).

Covers:
- Repository: is_banned/is_admin filters (independent + combined), username-asc
  ordering, pagination.
- Endpoint: 401 without/with wrong X-API-Key, 503 without ADMIN_API_KEY, filters,
  pagination metadata, response shape (no email).

The ``db`` fixture (see tests/conftest.py) gives each test a fully isolated
transaction (rolled back on teardown), so counts created within a test can be
asserted exactly without accounting for rows from other tests.
"""

from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.admin.repository import list_users
from backlogg.main import app
from backlogg.users.repository import create_user, set_user_admin, set_user_banned

_VALID_KEY = "test-admin-secret"


# ── Fixtures ───────────────────────────────────────────────────────────────────


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


@pytest_asyncio.fixture
async def client_no_env_key(db):
    """AsyncClient where ADMIN_API_KEY is not configured (empty string)."""
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = ""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


async def _make_user(db, username: str, *, is_banned: bool = False, is_admin: bool = False):
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username.title(),
        },
    )
    if is_banned:
        await set_user_banned(db, user, True)
    if is_admin:
        await set_user_admin(db, user, True)
    return user


def _admin() -> dict:
    return {"X-API-Key": _VALID_KEY}


# ── Repository: list_users ──────────────────────────────────────────────────


async def test_list_users_no_filters_returns_all(db):
    await _make_user(db, "aul-repo-charlie")
    await _make_user(db, "aul-repo-alice")
    await _make_user(db, "aul-repo-bob")

    users, total = await list_users(db, is_banned=None, is_admin=None, page=1, limit=50)

    assert total == 3
    assert [u.username for u in users] == ["aul-repo-alice", "aul-repo-bob", "aul-repo-charlie"]


async def test_list_users_filters_by_is_banned(db):
    await _make_user(db, "aul-repo-banned-1", is_banned=True)
    await _make_user(db, "aul-repo-clean-1")

    banned, banned_total = await list_users(db, is_banned=True, is_admin=None, page=1, limit=50)
    clean, clean_total = await list_users(db, is_banned=False, is_admin=None, page=1, limit=50)

    assert banned_total == 1
    assert [u.username for u in banned] == ["aul-repo-banned-1"]
    assert clean_total == 1
    assert [u.username for u in clean] == ["aul-repo-clean-1"]


async def test_list_users_filters_by_is_admin(db):
    await _make_user(db, "aul-repo-admin-1", is_admin=True)
    await _make_user(db, "aul-repo-plain-1")

    admins, admins_total = await list_users(db, is_banned=None, is_admin=True, page=1, limit=50)
    plain, plain_total = await list_users(db, is_banned=None, is_admin=False, page=1, limit=50)

    assert admins_total == 1
    assert [u.username for u in admins] == ["aul-repo-admin-1"]
    assert plain_total == 1
    assert [u.username for u in plain] == ["aul-repo-plain-1"]


async def test_list_users_combined_filters_are_independent(db):
    await _make_user(db, "aul-repo-combo-banned-admin", is_banned=True, is_admin=True)
    await _make_user(db, "aul-repo-combo-banned-only", is_banned=True, is_admin=False)
    await _make_user(db, "aul-repo-combo-admin-only", is_banned=False, is_admin=True)
    await _make_user(db, "aul-repo-combo-plain", is_banned=False, is_admin=False)

    banned_admins, total = await list_users(db, is_banned=True, is_admin=True, page=1, limit=50)

    assert total == 1
    assert [u.username for u in banned_admins] == ["aul-repo-combo-banned-admin"]


async def test_list_users_orders_by_username_asc(db):
    await _make_user(db, "aul-repo-order-zeta")
    await _make_user(db, "aul-repo-order-alpha")
    await _make_user(db, "aul-repo-order-mu")

    users, _ = await list_users(db, is_banned=None, is_admin=None, page=1, limit=50)

    usernames = [u.username for u in users]
    assert usernames == sorted(usernames)


async def test_list_users_paginates(db):
    for i in range(5):
        await _make_user(db, f"aul-repo-page-{i}")

    page1, total = await list_users(db, is_banned=None, is_admin=None, page=1, limit=2)
    page2, _ = await list_users(db, is_banned=None, is_admin=None, page=2, limit=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    # No overlap between pages, ordering preserved across pages.
    assert {u.username for u in page1}.isdisjoint({u.username for u in page2})


# ── Endpoint: GET /admin/users — auth gate ──────────────────────────────────


async def test_list_users_without_api_key_returns_401(client):
    response = await client.get("/v1/admin/users")
    assert response.status_code == 401


async def test_list_users_with_wrong_api_key_returns_401(client):
    response = await client.get("/v1/admin/users", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


async def test_list_users_no_env_key_returns_503(client_no_env_key):
    response = await client_no_env_key.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 503


async def test_list_users_with_correct_api_key_returns_200(client, db):
    await _make_user(db, "aul-route-basic-1")
    response = await client.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 200


# ── Endpoint: filters ────────────────────────────────────────────────────────


async def test_list_users_endpoint_filters_by_is_banned(client, db):
    await _make_user(db, "aul-route-banned-1", is_banned=True)
    await _make_user(db, "aul-route-clean-1")

    response = await client.get("/v1/admin/users?is_banned=true", headers=_admin())
    assert response.status_code == 200
    usernames = [item["username"] for item in response.json()["items"]]
    assert "aul-route-banned-1" in usernames
    assert "aul-route-clean-1" not in usernames


async def test_list_users_endpoint_filters_by_is_admin(client, db):
    await _make_user(db, "aul-route-admin-1", is_admin=True)
    await _make_user(db, "aul-route-plain-1")

    response = await client.get("/v1/admin/users?is_admin=true", headers=_admin())
    assert response.status_code == 200
    usernames = [item["username"] for item in response.json()["items"]]
    assert "aul-route-admin-1" in usernames
    assert "aul-route-plain-1" not in usernames


async def test_list_users_endpoint_combined_filters(client, db):
    await _make_user(db, "aul-route-combo-1", is_banned=True, is_admin=True)
    await _make_user(db, "aul-route-combo-2", is_banned=True, is_admin=False)

    response = await client.get("/v1/admin/users?is_banned=true&is_admin=true", headers=_admin())
    assert response.status_code == 200
    usernames = [item["username"] for item in response.json()["items"]]
    assert usernames == ["aul-route-combo-1"]


async def test_list_users_no_filters_returns_everyone(client, db):
    await _make_user(db, "aul-route-all-1", is_banned=True)
    await _make_user(db, "aul-route-all-2", is_admin=True)
    await _make_user(db, "aul-route-all-3")

    response = await client.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    usernames = {item["username"] for item in body["items"]}
    assert usernames == {"aul-route-all-1", "aul-route-all-2", "aul-route-all-3"}


# ── Endpoint: pagination metadata ───────────────────────────────────────────


async def test_list_users_pagination_metadata(client, db):
    for i in range(3):
        await _make_user(db, f"aul-route-page-{i}")

    response = await client.get("/v1/admin/users?page=1&limit=2", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2


# ── Endpoint: response shape ─────────────────────────────────────────────────


async def test_list_users_response_excludes_email(client, db):
    await _make_user(db, "aul-route-noemail-1")

    response = await client.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert "email" not in item


async def test_list_users_response_has_expected_fields(client, db):
    await _make_user(db, "aul-route-shape-1")

    response = await client.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 200
    item = next(i for i in response.json()["items"] if i["username"] == "aul-route-shape-1")
    assert set(item.keys()) == {
        "username",
        "display_name",
        "avatar_url",
        "is_admin",
        "is_superadmin",
        "is_banned",
        "created_at",
    }


async def test_list_users_response_ordered_by_username_asc(client, db):
    await _make_user(db, "aul-route-zzz")
    await _make_user(db, "aul-route-aaa")

    response = await client.get("/v1/admin/users", headers=_admin())
    assert response.status_code == 200
    usernames = [item["username"] for item in response.json()["items"]]
    assert usernames == sorted(usernames)
