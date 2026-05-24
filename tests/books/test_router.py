from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as repo
from backlogg.books import service
from backlogg.main import app


def _make_book_dict(slug: str = "the-hobbit-1937") -> dict:
    return {
        "title": "The Hobbit",
        "original_title": None,
        "slug": slug,
        "overview": "A hobbit goes on an adventure.",
        "first_publish_date": date(1937, 9, 21),
        "original_language": "en",
        "poster_url": "https://covers.openlibrary.org/b/id/12345-L.jpg",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Fantasy", "slug": "fantasy"}],
    }


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


async def test_get_book_returns_200(client, db):
    """GET /books/{slug} returns 200 with correct fields for a seeded book."""
    await repo.upsert_book(db, _make_book_dict("the-hobbit-1937"))

    response = await client.get("/books/the-hobbit-1937")
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == "the-hobbit-1937"
    assert body["title"] == "The Hobbit"
    assert body["first_publish_date"] == "1937-09-21"
    assert len(body["genres"]) == 1
    assert body["genres"][0]["name"] == "Fantasy"


async def test_get_book_returns_404(client, db):
    """GET /books/{slug} returns 404 when not in DB and Open Library has nothing."""
    with patch.object(service._ol_client, "search_book", new_callable=AsyncMock, return_value=None):
        response = await client.get("/books/nonexistent-slug-404-test")

    assert response.status_code == 404
