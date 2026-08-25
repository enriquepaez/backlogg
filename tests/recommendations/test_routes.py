"""Endpoint tests for GET /recommendations.

Covers auth enforcement (401 without token), the ``?type=`` validation
(422 on an invalid value), and a happy-path smoke test through the router.
"""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books.repository import upsert_book
from backlogg.main import app


def _book_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": date(2019, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": 8.0,
        "rating_count_external": 500,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


@pytest_asyncio.fixture
async def client(db):
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


async def test_recommendations_without_token_returns_401(client):
    response = await client.get("/v1/recommendations")
    assert response.status_code == 401


async def test_recommendations_invalid_type_returns_422(client):
    token = await _register_and_login(client, "rec-route-user-1")
    response = await client.get("/v1/recommendations?type=podcast", headers=_auth_headers(token))
    assert response.status_code == 422


async def test_recommendations_happy_path_fallback(client, db):
    await upsert_book(db, _book_data("rec-route-book-1", "Rec Route Book 1"))
    token = await _register_and_login(client, "rec-route-user-2")

    response = await client.get("/v1/recommendations?type=book", headers=_auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 20
    slugs = {r["slug"] for r in body["results"]}
    assert "rec-route-book-1" in slugs
    sample = body["results"][0]
    assert set(sample.keys()) == {
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
        "rating_internal",
        "reason",
    }
