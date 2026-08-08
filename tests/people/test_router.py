"""Tests for GET /people/{slug} via TestClient against real test DB."""

from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.people.repository import upsert_credit, upsert_person


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


def _now() -> datetime:
    return datetime.now(UTC)


async def test_get_person_returns_200(client, db):
    """GET /people/{slug} returns 200 with correct fields."""
    person = await upsert_person(
        db,
        {
            "name": "Tom Hanks",
            "slug": "tom-hanks-router-test",
            "profile_url": "https://example.com/tom.jpg",
            "last_synced_at": _now(),
        },
    )

    response = await client.get("/v1/people/tom-hanks-router-test")
    assert response.status_code == 200

    body = response.json()
    assert body["id"] == person.id
    assert body["name"] == "Tom Hanks"
    assert body["slug"] == "tom-hanks-router-test"
    assert body["profile_url"] == "https://example.com/tom.jpg"
    assert body["credits"] == []


async def test_get_person_returns_200_with_credits(client, db):
    """GET /people/{slug} returns credits list."""
    from datetime import UTC, datetime

    from backlogg.movies.repository import upsert_movie

    # Seed a movie
    movie = await upsert_movie(
        db,
        {
            "title": "Router Test Movie",
            "original_title": "Router Test Movie",
            "slug": "router-test-movie-2024",
            "overview": None,
            "release_date": None,
            "runtime": 120,
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
        },
    )

    # Seed a person
    person = await upsert_person(
        db,
        {
            "name": "Morgan Freeman",
            "slug": "morgan-freeman-router-test",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )

    # Create credit
    await upsert_credit(
        db,
        {
            "item_type": "MOVIE",
            "item_id": movie.id,
            "person_id": person.id,
            "role": "ACTOR",
            "character_name": "Narrator",
            "billing_order": 2,
        },
    )

    response = await client.get("/v1/people/morgan-freeman-router-test")
    assert response.status_code == 200

    body = response.json()
    assert body["name"] == "Morgan Freeman"
    assert len(body["credits"]) == 1
    credit = body["credits"][0]
    assert credit["item_type"] == "MOVIE"
    assert credit["item_slug"] == "router-test-movie-2024"
    assert credit["item_title"] == "Router Test Movie"
    assert credit["role"] == "ACTOR"
    assert credit["character_name"] == "Narrator"
    assert credit["billing_order"] == 2


async def test_get_person_returns_404(client, db):
    """GET /people/{slug} returns 404 for unknown slug."""
    response = await client.get("/v1/people/nobody-here-absolutely-999xyz")
    assert response.status_code == 404
