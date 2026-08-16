from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as repo
from backlogg.main import app


def _make_book_dict(slug: str) -> dict:
    return {
        "title": "Router Test Book",
        "original_title": None,
        "slug": slug,
        "overview": "A test book.",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
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


async def test_get_similar_books_returns_200(client, db):
    """GET /books/{slug}/similar returns 200 with results[] for a seeded book."""
    await repo.upsert_book(db, _make_book_dict("similar-router-source-book-2001"))

    response = await client.get("/v1/books/similar-router-source-book-2001/similar")

    assert response.status_code == 200
    assert response.json() == {"results": []}


async def test_get_similar_books_returns_404(client, db):
    """GET /books/{slug}/similar returns 404 when the source book is unknown."""
    response = await client.get("/v1/books/similar-router-unknown-slug-404/similar")

    assert response.status_code == 404
