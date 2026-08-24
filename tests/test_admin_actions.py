"""Tests for the admin action audit log (feature 63 — admin_action_audit_log).

Covers:
- Repository: insert_admin_action persists the expected row; list_admin_actions
  orders newest first and paginates.
- Endpoint auth gate: GET /v1/admin/actions requires X-API-Key (401 missing/
  wrong, 503 unconfigured), same as the rest of /v1/admin/*.
- Endpoint pagination metadata.
- Integration: each of the 4 audited action families writes a row —
  hide/unhide review, ban/unban user, resolve report (actor_id always None,
  X-API-Key-only routes) and grant/revoke-admin (actor_id set to the calling
  superadmin, the one audited route with a Bearer identity).

The ``db`` fixture (see tests/conftest.py) gives each test a fully isolated
transaction (rolled back on teardown), so ``total``/row counts created within
a test can be asserted exactly without accounting for rows from other tests.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.admin import repository as admin_repo
from backlogg.main import app
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.users import repository as users_repo
from backlogg.users.repository import create_user

_VALID_KEY = "test-admin-secret"


# ── Fixtures ─────────────────────────────────────────────────────────────────


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


def _movie_data(slug: str, title: str = "Audit Log Movie") -> dict:
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


async def _seed_review(db, slug: str, author_username: str) -> int:
    """Create an author + a movie + a review (UserRating). Returns the rating id."""
    author = await create_user(
        db,
        {
            "username": author_username,
            "email": f"{author_username}@example.com",
            "password_hash": "hash",
            "display_name": author_username,
        },
    )
    movie = await upsert_movie(db, _movie_data(slug))
    rating = await upsert_rating(
        db, user_id=author.id, item_type="MOVIE", item_id=movie.id, score=4, review_text="review"
    )
    await db.commit()
    return rating.id


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
    user = await users_repo.get_user_by_username(db, username)
    user.is_superadmin = True
    await db.flush()


# ── Repository: insert_admin_action / list_admin_actions ───────────────────


async def test_insert_admin_action_persists_expected_fields(db):
    action = await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=123
    )
    await db.commit()

    assert action.id is not None
    assert action.actor_id is None
    assert action.action == "ban_user"
    assert action.target_type == "user"
    assert action.target_id == 123
    assert action.created_at is not None


async def test_insert_admin_action_with_actor_id(db):
    actor = await create_user(
        db,
        {
            "username": "aaa-repo-actor-1",
            "email": "aaa-repo-actor-1@example.com",
            "password_hash": "hash",
        },
    )
    action = await admin_repo.insert_admin_action(
        db, actor_id=actor.id, action="grant_admin", target_type="user", target_id=999
    )
    await db.commit()

    assert action.actor_id == actor.id


async def test_list_admin_actions_orders_newest_first(db):
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="hide_review", target_type="review", target_id=1
    )
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="unhide_review", target_type="review", target_id=1
    )
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=2
    )
    await db.commit()

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=50)

    assert total == 3
    assert [a.action for a in actions] == ["ban_user", "unhide_review", "hide_review"]


async def test_list_admin_actions_paginates(db):
    for i in range(5):
        await admin_repo.insert_admin_action(
            db, actor_id=None, action="resolve_report", target_type="report", target_id=i
        )
    await db.commit()

    page1, total = await admin_repo.list_admin_actions(db, page=1, limit=2)
    page2, _ = await admin_repo.list_admin_actions(db, page=2, limit=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {a.id for a in page1}.isdisjoint({a.id for a in page2})


# ── Endpoint: GET /v1/admin/actions — auth gate ─────────────────────────────


async def test_list_actions_without_api_key_returns_401(client):
    response = await client.get("/v1/admin/actions")
    assert response.status_code == 401


async def test_list_actions_with_wrong_api_key_returns_401(client):
    response = await client.get("/v1/admin/actions", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


async def test_list_actions_no_env_key_returns_503(client_no_env_key):
    response = await client_no_env_key.get("/v1/admin/actions", headers=_admin())
    assert response.status_code == 503


async def test_list_actions_with_correct_api_key_returns_200(client, db):
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=1
    )
    await db.commit()

    response = await client.get("/v1/admin/actions", headers=_admin())
    assert response.status_code == 200


# ── Endpoint: pagination + response shape ───────────────────────────────────


async def test_list_actions_pagination_metadata(client, db):
    for i in range(3):
        await admin_repo.insert_admin_action(
            db, actor_id=None, action="ban_user", target_type="user", target_id=i
        )
    await db.commit()

    response = await client.get("/v1/admin/actions?page=1&limit=2", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_list_actions_response_ordered_newest_first(client, db):
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=1
    )
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="unban_user", target_type="user", target_id=1
    )
    await db.commit()

    response = await client.get("/v1/admin/actions", headers=_admin())
    assert response.status_code == 200
    actions = [item["action"] for item in response.json()["items"]]
    assert actions == ["unban_user", "ban_user"]


async def test_list_actions_response_has_expected_fields(client, db):
    await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=1
    )
    await db.commit()

    response = await client.get("/v1/admin/actions", headers=_admin())
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item.keys()) == {
        "id",
        "actor_id",
        "action",
        "target_type",
        "target_id",
        "created_at",
    }


# ── Integration: hide/unhide review writes an audit row ────────────────────


async def test_hide_review_writes_audit_row(client, db):
    rating_id = await _seed_review(db, "aud-hide-movie-1", "aud-hide-author-1")

    response = await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "hide_review"
    assert actions[0].target_type == "review"
    assert actions[0].target_id == rating_id
    assert actions[0].actor_id is None


async def test_unhide_review_writes_audit_row(client, db):
    rating_id = await _seed_review(db, "aud-hide-movie-2", "aud-hide-author-2")
    await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())

    response = await client.post(f"/v1/admin/reviews/{rating_id}/unhide", headers=_admin())
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 2
    assert actions[0].action == "unhide_review"
    assert actions[0].target_id == rating_id
    assert actions[0].actor_id is None


# ── Integration: ban/unban user writes an audit row ─────────────────────────


async def test_ban_user_writes_audit_row(client, db):
    await _register_and_login(client, "aud-ban-user-1")
    user = await users_repo.get_user_by_username(db, "aud-ban-user-1")

    response = await client.post("/v1/admin/users/aud-ban-user-1/ban", headers=_admin())
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "ban_user"
    assert actions[0].target_type == "user"
    assert actions[0].target_id == user.id
    assert actions[0].actor_id is None


async def test_unban_user_writes_audit_row(client, db):
    await _register_and_login(client, "aud-ban-user-2")
    user = await users_repo.get_user_by_username(db, "aud-ban-user-2")
    await client.post("/v1/admin/users/aud-ban-user-2/ban", headers=_admin())

    response = await client.post("/v1/admin/users/aud-ban-user-2/unban", headers=_admin())
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 2
    assert actions[0].action == "unban_user"
    assert actions[0].target_id == user.id
    assert actions[0].actor_id is None


# ── Integration: resolve report writes an audit row ─────────────────────────


async def test_resolve_report_writes_audit_row(client, db):
    rating_id = await _seed_review(db, "aud-report-movie-1", "aud-report-author-1")
    reporter_token = await _register_and_login(client, "aud-report-reporter-1")
    created = await client.post(
        f"/v1/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(reporter_token)
    )
    report_id = created.json()["id"]

    response = await client.post(f"/v1/admin/reports/{report_id}/resolve", headers=_admin())
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "resolve_report"
    assert actions[0].target_type == "report"
    assert actions[0].target_id == report_id
    assert actions[0].actor_id is None


# ── Integration: grant/revoke-admin writes an audit row with actor_id set ──


async def test_grant_admin_writes_audit_row_with_actor_id(client, db):
    caller_token = await _register_and_login(client, "aud-role-super-1")
    await _make_superadmin(db, "aud-role-super-1")
    caller = await users_repo.get_user_by_username(db, "aud-role-super-1")
    await _register_and_login(client, "aud-role-target-1")
    target = await users_repo.get_user_by_username(db, "aud-role-target-1")

    response = await client.post(
        "/v1/admin/users/aud-role-target-1/grant-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "grant_admin"
    assert actions[0].target_type == "user"
    assert actions[0].target_id == target.id
    assert actions[0].actor_id == caller.id


async def test_revoke_admin_writes_audit_row_with_actor_id(client, db):
    caller_token = await _register_and_login(client, "aud-role-super-2")
    await _make_superadmin(db, "aud-role-super-2")
    caller = await users_repo.get_user_by_username(db, "aud-role-super-2")
    await _register_and_login(client, "aud-role-target-2")
    target = await users_repo.get_user_by_username(db, "aud-role-target-2")
    await users_repo.set_user_admin(db, target, True)

    response = await client.post(
        "/v1/admin/users/aud-role-target-2/revoke-admin", headers=_admin_auth(caller_token)
    )
    assert response.status_code == 200

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "revoke_admin"
    assert actions[0].target_id == target.id
    assert actions[0].actor_id == caller.id


# ── Service: direct calls (bypassing the route layer) ──────────────────────


async def test_service_list_admin_actions_returns_expected_shape(db):
    from backlogg.admin import service as admin_service

    await admin_repo.insert_admin_action(
        db, actor_id=None, action="ban_user", target_type="user", target_id=1
    )
    await db.commit()

    result = await admin_service.list_admin_actions(db, page=1, limit=20)

    assert result.total == 1
    assert result.items[0].action == "ban_user"


async def test_service_set_review_hidden_records_audit_row(db):
    from backlogg.moderation import service as moderation_service

    rating_id = await _seed_review(db, "aud-svc-movie-1", "aud-svc-author-1")

    await moderation_service.set_review_hidden(db, rating_id=rating_id, hidden=True)

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "hide_review"
    assert actions[0].target_id == rating_id


async def test_service_resolve_report_records_audit_row(db):
    from backlogg.reports import repository as reports_repo
    from backlogg.reports import service as reports_service

    rating_id = await _seed_review(db, "aud-svc-movie-2", "aud-svc-author-2")
    reporter = await create_user(
        db,
        {
            "username": "aud-svc-reporter-2",
            "email": "aud-svc-reporter-2@example.com",
            "password_hash": "hash",
        },
    )
    report, _created = await reports_repo.create_report_if_not_exists(
        db, reporter_id=reporter.id, rating_id=rating_id, reason=None
    )
    await db.commit()

    await reports_service.resolve_report(db, report_id=report.id)

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "resolve_report"
    assert actions[0].target_id == report.id


async def test_service_set_user_admin_role_records_audit_row_with_actor(db):
    from backlogg.admin import service as admin_service

    caller = await create_user(
        db,
        {
            "username": "aud-svc-caller-1",
            "email": "aud-svc-caller-1@example.com",
            "password_hash": "hash",
        },
    )
    caller.is_superadmin = True
    target = await create_user(
        db,
        {
            "username": "aud-svc-target-1",
            "email": "aud-svc-target-1@example.com",
            "password_hash": "hash",
        },
    )
    await db.flush()

    await admin_service.set_user_admin_role(db, caller, target.username, is_admin=True)

    actions, total = await admin_repo.list_admin_actions(db, page=1, limit=10)
    assert total == 1
    assert actions[0].action == "grant_admin"
    assert actions[0].target_id == target.id
    assert actions[0].actor_id == caller.id


# ── GET /v1/admin/actions surfaces actions from all 4 families ─────────────


async def test_list_actions_surfaces_all_action_families(client, db):
    rating_id = await _seed_review(db, "aud-mix-movie-1", "aud-mix-author-1")
    await client.post(f"/v1/admin/reviews/{rating_id}/hide", headers=_admin())

    await _register_and_login(client, "aud-mix-banned-1")
    await client.post("/v1/admin/users/aud-mix-banned-1/ban", headers=_admin())

    reporter_token = await _register_and_login(client, "aud-mix-reporter-1")
    created = await client.post(
        f"/v1/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(reporter_token)
    )
    await client.post(f"/v1/admin/reports/{created.json()['id']}/resolve", headers=_admin())

    caller_token = await _register_and_login(client, "aud-mix-super-1")
    await _make_superadmin(db, "aud-mix-super-1")
    await _register_and_login(client, "aud-mix-target-1")
    await client.post(
        "/v1/admin/users/aud-mix-target-1/grant-admin", headers=_admin_auth(caller_token)
    )

    response = await client.get("/v1/admin/actions", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    actions = {item["action"] for item in body["items"]}
    assert actions == {"hide_review", "ban_user", "resolve_report", "grant_admin"}
