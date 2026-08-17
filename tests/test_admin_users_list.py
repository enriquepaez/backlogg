"""Tests for GET /admin/users and GET /admin/users/{username} (feature 48 —
admin_users_list — plus a small backend extension for the admin user detail
page, tracked outside feature_list.json, see progress/impl_admin_user_detail_backend.md).

Covers:
- Repository: is_banned/is_admin filters (independent + combined), username-asc
  ordering, pagination.
- Endpoint (list): 401 without/with wrong X-API-Key, 503 without ADMIN_API_KEY,
  filters, pagination metadata, response shape (no email).
- Service (detail): found/not-found (404) for ``admin_service.get_user``.
- Endpoint (detail): 401 without/with wrong X-API-Key, 503 without
  ADMIN_API_KEY, 200 happy path, 404 unknown username, response shape.

The ``db`` fixture (see tests/conftest.py) gives each test a fully isolated
transaction (rolled back on teardown), so counts created within a test can be
asserted exactly without accounting for rows from other tests.
"""

from unittest.mock import patch

import pytest
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


async def _make_user(
    db,
    username: str,
    *,
    is_banned: bool = False,
    is_admin: bool = False,
    display_name: str | None = None,
    email: str | None = None,
):
    user = await create_user(
        db,
        {
            "username": username,
            "email": email or f"{username}@example.com",
            "password_hash": "hash",
            "display_name": display_name if display_name is not None else username.title(),
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

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search=None, page=1, limit=50
    )

    assert total == 3
    assert [u.username for u in users] == ["aul-repo-alice", "aul-repo-bob", "aul-repo-charlie"]


async def test_list_users_filters_by_is_banned(db):
    await _make_user(db, "aul-repo-banned-1", is_banned=True)
    await _make_user(db, "aul-repo-clean-1")

    banned, banned_total = await list_users(
        db, is_banned=True, is_admin=None, search=None, page=1, limit=50
    )
    clean, clean_total = await list_users(
        db, is_banned=False, is_admin=None, search=None, page=1, limit=50
    )

    assert banned_total == 1
    assert [u.username for u in banned] == ["aul-repo-banned-1"]
    assert clean_total == 1
    assert [u.username for u in clean] == ["aul-repo-clean-1"]


async def test_list_users_filters_by_is_admin(db):
    await _make_user(db, "aul-repo-admin-1", is_admin=True)
    await _make_user(db, "aul-repo-plain-1")

    admins, admins_total = await list_users(
        db, is_banned=None, is_admin=True, search=None, page=1, limit=50
    )
    plain, plain_total = await list_users(
        db, is_banned=None, is_admin=False, search=None, page=1, limit=50
    )

    assert admins_total == 1
    assert [u.username for u in admins] == ["aul-repo-admin-1"]
    assert plain_total == 1
    assert [u.username for u in plain] == ["aul-repo-plain-1"]


async def test_list_users_combined_filters_are_independent(db):
    await _make_user(db, "aul-repo-combo-banned-admin", is_banned=True, is_admin=True)
    await _make_user(db, "aul-repo-combo-banned-only", is_banned=True, is_admin=False)
    await _make_user(db, "aul-repo-combo-admin-only", is_banned=False, is_admin=True)
    await _make_user(db, "aul-repo-combo-plain", is_banned=False, is_admin=False)

    banned_admins, total = await list_users(
        db, is_banned=True, is_admin=True, search=None, page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in banned_admins] == ["aul-repo-combo-banned-admin"]


async def test_list_users_orders_by_username_asc(db):
    await _make_user(db, "aul-repo-order-zeta")
    await _make_user(db, "aul-repo-order-alpha")
    await _make_user(db, "aul-repo-order-mu")

    users, _ = await list_users(db, is_banned=None, is_admin=None, search=None, page=1, limit=50)

    usernames = [u.username for u in users]
    assert usernames == sorted(usernames)


async def test_list_users_paginates(db):
    for i in range(5):
        await _make_user(db, f"aul-repo-page-{i}")

    page1, total = await list_users(db, is_banned=None, is_admin=None, search=None, page=1, limit=2)
    page2, _ = await list_users(db, is_banned=None, is_admin=None, search=None, page=2, limit=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    # No overlap between pages, ordering preserved across pages.
    assert {u.username for u in page1}.isdisjoint({u.username for u in page2})


# ── Repository: list_users — search ─────────────────────────────────────────


async def test_list_users_search_matches_username(db):
    await _make_user(db, "aul-repo-search-dexter")
    await _make_user(db, "aul-repo-search-other")

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search="dexter", page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in users] == ["aul-repo-search-dexter"]


async def test_list_users_search_matches_display_name(db):
    await _make_user(db, "aul-repo-search-dn-1", display_name="Morgan Chase")
    await _make_user(db, "aul-repo-search-dn-2", display_name="Someone Else")

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search="morgan", page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in users] == ["aul-repo-search-dn-1"]


async def test_list_users_search_matches_email(db):
    await _make_user(db, "aul-repo-search-em-1", email="findme-uniquetoken@example.com")
    await _make_user(db, "aul-repo-search-em-2", email="other-uniquetoken@example.com")

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search="findme-uniquetoken", page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in users] == ["aul-repo-search-em-1"]


async def test_list_users_search_is_case_insensitive(db):
    await _make_user(db, "aul-repo-search-case-1")

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search="SEARCH-CASE", page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in users] == ["aul-repo-search-case-1"]


async def test_list_users_search_no_match_returns_empty(db):
    await _make_user(db, "aul-repo-search-nomatch-1")

    users, total = await list_users(
        db, is_banned=None, is_admin=None, search="zzz-nonexistent-zzz", page=1, limit=50
    )

    assert total == 0
    assert users == []


async def test_list_users_search_combined_with_is_banned(db):
    await _make_user(db, "aul-repo-search-combo-1", is_banned=True)
    await _make_user(db, "aul-repo-search-combo-2", is_banned=False)

    users, total = await list_users(
        db, is_banned=True, is_admin=None, search="aul-repo-search-combo", page=1, limit=50
    )

    assert total == 1
    assert [u.username for u in users] == ["aul-repo-search-combo-1"]


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


async def test_list_users_endpoint_filters_by_search(client, db):
    await _make_user(db, "aul-route-search-1")
    await _make_user(db, "aul-route-other-1")

    response = await client.get("/v1/admin/users?search=aul-route-search-1", headers=_admin())
    assert response.status_code == 200
    usernames = [item["username"] for item in response.json()["items"]]
    assert usernames == ["aul-route-search-1"]


async def test_list_users_endpoint_empty_search_returns_everyone(client, db):
    await _make_user(db, "aul-route-emptysearch-1")
    await _make_user(db, "aul-route-emptysearch-2")

    response = await client.get("/v1/admin/users?search=", headers=_admin())
    assert response.status_code == 200
    usernames = {item["username"] for item in response.json()["items"]}
    assert {"aul-route-emptysearch-1", "aul-route-emptysearch-2"}.issubset(usernames)


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


# ── Service: get_user ────────────────────────────────────────────────────────


async def test_get_user_returns_admin_user_out(db):
    from backlogg.admin.service import get_user

    await _make_user(db, "aud-svc-found-1")

    result = await get_user(db, "aud-svc-found-1")

    assert result.username == "aud-svc-found-1"
    assert result.is_admin is False
    assert result.is_banned is False


async def test_get_user_unknown_username_raises_404(db):
    from fastapi import HTTPException

    from backlogg.admin.service import get_user

    with pytest.raises(HTTPException) as exc_info:
        await get_user(db, "aud-svc-nobody")
    assert exc_info.value.status_code == 404


# ── Endpoint: GET /admin/users/{username} — auth gate ───────────────────────


async def test_get_user_without_api_key_returns_401(client):
    response = await client.get("/v1/admin/users/whoever")
    assert response.status_code == 401


async def test_get_user_with_wrong_api_key_returns_401(client):
    response = await client.get("/v1/admin/users/whoever", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


async def test_get_user_no_env_key_returns_503(client_no_env_key):
    response = await client_no_env_key.get("/v1/admin/users/whoever", headers=_admin())
    assert response.status_code == 503


# ── Endpoint: GET /admin/users/{username} — happy path / 404 ────────────────


async def test_get_user_with_correct_api_key_returns_200(client, db):
    await _make_user(db, "aud-route-basic-1", is_admin=True)

    response = await client.get("/v1/admin/users/aud-route-basic-1", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "aud-route-basic-1"
    assert body["is_admin"] is True
    assert "email" not in body


async def test_get_user_unknown_username_returns_404(client, db):
    response = await client.get("/v1/admin/users/aud-route-nobody", headers=_admin())
    assert response.status_code == 404


async def test_get_user_response_has_expected_fields(client, db):
    await _make_user(db, "aud-route-shape-1")

    response = await client.get("/v1/admin/users/aud-route-shape-1", headers=_admin())
    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "username",
        "display_name",
        "avatar_url",
        "is_admin",
        "is_superadmin",
        "is_banned",
        "created_at",
    }
