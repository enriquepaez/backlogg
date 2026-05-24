from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.series import repository as repo
from backlogg.series import service


def _make_series_dict(slug: str = "the-wire-2002") -> dict:
    return {
        "title": "The Wire",
        "original_title": "The Wire",
        "slug": slug,
        "overview": "The Baltimore drug scene through the eyes of police and criminals.",
        "first_air_date": date(2002, 6, 2),
        "last_air_date": date(2008, 3, 9),
        "number_of_seasons": 5,
        "number_of_episodes": 60,
        "status": "Ended",
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/thewire.jpg",
        "backdrop_url": None,
        "rating_external": 9.3,
        "rating_count_external": 8000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Drama", "slug": "drama"}, {"name": "Crime", "slug": "crime"}],
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


async def test_get_series_found(client, db):
    """GET /series/{slug} returns 200 with correct fields for a seeded series."""
    # Seed the series directly via repository
    await repo.upsert_series(db, _make_series_dict("the-wire-2002"))

    response = await client.get("/series/the-wire-2002")
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == "the-wire-2002"
    assert body["title"] == "The Wire"
    assert body["first_air_date"] == "2002-06-02"
    assert body["number_of_seasons"] == 5
    assert body["number_of_episodes"] == 60
    assert len(body["genres"]) == 2
    genre_names = {g["name"] for g in body["genres"]}
    assert genre_names == {"Drama", "Crime"}


async def test_get_series_returns_404(client, db):
    """GET /series/{slug} returns 404 when not in DB and TMDB also has nothing."""
    with (
        patch.object(service._tmdb, "search_series", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.get("/series/nonexistent-slug-404-test")

    assert response.status_code == 404
