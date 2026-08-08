"""Endpoint tests for the review_reports feature.

Covers:
- POST /reviews/{id}/report (auth, idempotent, 404, 401).
- GET /admin/reports (X-API-Key, status filter, pagination).
- POST /admin/reports/{id}/resolve (X-API-Key, 404).
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.users.repository import create_user

_VALID_KEY = "test-admin-secret"


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the FastAPI app, using the test DB session.

    Also patches the admin auth settings so /admin/* endpoints accept
    ``_VALID_KEY`` via the X-API-Key header.
    """
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


def _movie_data(slug: str, title: str = "Report Route Movie") -> dict:
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
        db,
        user_id=author.id,
        item_type="MOVIE",
        item_id=movie.id,
        score=4,
        review_text="reported review",
    )
    await db.commit()
    return rating.id


async def _register_and_login(client: AsyncClient, username: str) -> str:
    await client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pw"},
    )
    login = await client.post("/auth/login", json={"username": username, "password": "s3cret-pw"})
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin() -> dict:
    return {"X-API-Key": _VALID_KEY}


# ── POST /reviews/{id}/report ────────────────────────────────────────────


async def test_report_without_token_returns_401(client, db):
    rating_id = await _seed_review(db, "report-route-movie-1", "report-route-author-1")
    response = await client.post(f"/reviews/{rating_id}/report", json={"reason": "spam"})
    assert response.status_code == 401


async def test_report_returns_201_first_time(client, db):
    rating_id = await _seed_review(db, "report-route-movie-2", "report-route-author-2")
    token = await _register_and_login(client, "report-route-reporter-2")

    response = await client.post(
        f"/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(token)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["rating_id"] == rating_id
    assert body["reason"] == "spam"
    assert body["status"] == "open"


async def test_report_without_body_is_accepted(client, db):
    rating_id = await _seed_review(db, "report-route-movie-3", "report-route-author-3")
    token = await _register_and_login(client, "report-route-reporter-3")

    response = await client.post(f"/reviews/{rating_id}/report", headers=_auth(token))
    assert response.status_code == 201
    assert response.json()["reason"] is None


async def test_report_twice_is_idempotent_returns_200(client, db):
    rating_id = await _seed_review(db, "report-route-movie-4", "report-route-author-4")
    token = await _register_and_login(client, "report-route-reporter-4")

    first = await client.post(
        f"/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(token)
    )
    second = await client.post(
        f"/reviews/{rating_id}/report", json={"reason": "again"}, headers=_auth(token)
    )
    assert first.status_code == 201
    assert second.status_code == 200
    # Same report row; original reason preserved.
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["reason"] == "spam"


async def test_report_unknown_review_returns_404(client):
    token = await _register_and_login(client, "report-route-reporter-5")
    response = await client.post(
        "/reviews/999999999/report", json={"reason": "x"}, headers=_auth(token)
    )
    assert response.status_code == 404


# ── GET /admin/reports ───────────────────────────────────────────────────


async def test_list_reports_without_key_returns_401(client):
    response = await client.get("/admin/reports")
    assert response.status_code == 401


async def test_list_reports_returns_reports(client, db):
    rating_id = await _seed_review(db, "report-route-movie-6", "report-route-author-6")
    token = await _register_and_login(client, "report-route-reporter-6")
    await client.post(f"/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(token))

    response = await client.get("/admin/reports", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(item["rating_id"] == rating_id for item in body["items"])


async def test_list_reports_status_filter(client, db):
    rating_id = await _seed_review(db, "report-route-movie-7", "report-route-author-7")
    token = await _register_and_login(client, "report-route-reporter-7")
    created = await client.post(
        f"/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(token)
    )
    report_id = created.json()["id"]

    open_list = await client.get("/admin/reports?status=open", headers=_admin())
    assert any(i["id"] == report_id for i in open_list.json()["items"])

    resolved_list = await client.get("/admin/reports?status=resolved", headers=_admin())
    assert all(i["id"] != report_id for i in resolved_list.json()["items"])


async def test_list_reports_pagination(client, db):
    response = await client.get("/admin/reports?page=1&limit=5", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 5


# ── POST /admin/reports/{id}/resolve ─────────────────────────────────────


async def test_resolve_without_key_returns_401(client):
    response = await client.post("/admin/reports/1/resolve")
    assert response.status_code == 401


async def test_resolve_marks_report_resolved(client, db):
    rating_id = await _seed_review(db, "report-route-movie-8", "report-route-author-8")
    token = await _register_and_login(client, "report-route-reporter-8")
    created = await client.post(
        f"/reviews/{rating_id}/report", json={"reason": "spam"}, headers=_auth(token)
    )
    report_id = created.json()["id"]

    response = await client.post(f"/admin/reports/{report_id}/resolve", headers=_admin())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None


async def test_resolve_unknown_report_returns_404(client):
    response = await client.post("/admin/reports/777777777/resolve", headers=_admin())
    assert response.status_code == 404
