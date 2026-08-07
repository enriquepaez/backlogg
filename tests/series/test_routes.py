from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.people import repository as people_repo
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
    assert body["rating_internal"] is None
    assert body["rating_count_internal"] == 0


async def test_get_series_returns_404(client, db):
    """GET /series/{slug} returns 404 when not in DB and TMDB also has nothing."""
    with (
        patch.object(service._tmdb, "search_series", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.get("/series/nonexistent-slug-404-test")

    assert response.status_code == 404


async def test_get_series_credits_empty(client, db):
    """GET /series/{slug} returns credits as [] when no credits exist."""
    await repo.upsert_series(db, _make_series_dict("credits-empty-series-2002"))

    response = await client.get("/series/credits-empty-series-2002")
    assert response.status_code == 200

    body = response.json()
    assert "credits" in body
    assert body["credits"] == []


async def test_get_series_credits_present_and_ordered(client, db):
    """GET /series/{slug} returns credits ordered by billing_order ascending."""
    series = await repo.upsert_series(db, _make_series_dict("credits-ordered-series-2002"))
    now = datetime.now(UTC)

    person_a = await people_repo.upsert_person(
        db,
        {
            "name": "Series Actor A",
            "slug": "series-actor-a-credits-test",
            "profile_url": "https://example.com/sa.jpg",
            "last_synced_at": now,
        },
    )
    person_b = await people_repo.upsert_person(
        db,
        {
            "name": "Series Actor B",
            "slug": "series-actor-b-credits-test",
            "profile_url": None,
            "last_synced_at": now,
        },
    )
    await people_repo.upsert_credit(
        db,
        {
            "item_type": "SERIES",
            "item_id": series.id,
            "person_id": person_b.id,
            "role": "ACTOR",
            "character_name": "Bob",
            "billing_order": 2,
        },
    )
    await people_repo.upsert_credit(
        db,
        {
            "item_type": "SERIES",
            "item_id": series.id,
            "person_id": person_a.id,
            "role": "ACTOR",
            "character_name": "Alice",
            "billing_order": 1,
        },
    )

    response = await client.get("/series/credits-ordered-series-2002")
    assert response.status_code == 200

    body = response.json()
    credits = body["credits"]
    assert len(credits) == 2
    assert credits[0]["person_name"] == "Series Actor A"
    assert credits[0]["person_slug"] == "series-actor-a-credits-test"
    assert credits[0]["profile_url"] == "https://example.com/sa.jpg"
    assert credits[0]["role"] == "ACTOR"
    assert credits[0]["character_name"] == "Alice"
    assert credits[0]["billing_order"] == 1
    assert credits[1]["person_name"] == "Series Actor B"
    assert credits[1]["billing_order"] == 2
