from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as repo
from backlogg.movies import service


def _make_movie_dict(slug: str = "the-matrix-1999") -> dict:
    return {
        "title": "The Matrix",
        "original_title": "The Matrix",
        "slug": slug,
        "overview": "A computer hacker learns about the true nature of reality.",
        "release_date": date(1999, 3, 31),
        "runtime": 136,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/matrix.jpg",
        "backdrop_url": None,
        "budget": 63000000,
        "revenue": 463517383,
        "status": "Released",
        "rating_external": 8.2,
        "rating_count_external": 20000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Action", "slug": "action"}, {"name": "Sci-Fi", "slug": "sci-fi"}],
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


async def test_get_movie_returns_200(client, db):
    """GET /movies/{slug} returns 200 with correct fields for a seeded movie."""
    # Seed the movie directly via repository
    await repo.upsert_movie(db, _make_movie_dict("the-matrix-1999"))

    response = await client.get("/movies/the-matrix-1999")
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == "the-matrix-1999"
    assert body["title"] == "The Matrix"
    assert body["release_date"] == "1999-03-31"
    assert len(body["genres"]) == 2
    genre_names = {g["name"] for g in body["genres"]}
    assert genre_names == {"Action", "Sci-Fi"}


async def test_get_movie_returns_404(client, db):
    """GET /movies/{slug} returns 404 when not in DB and TMDB also has nothing."""
    with (
        patch.object(service._tmdb, "search_movie", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.get("/movies/nonexistent-slug-404-test")

    assert response.status_code == 404
