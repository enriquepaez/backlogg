from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as repo
from backlogg.movies import service
from backlogg.people import repository as people_repo
from backlogg.shared.credits import build_cast_payload, upsert_item_cast


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

    response = await client.get("/v1/movies/the-matrix-1999")
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == "the-matrix-1999"
    assert body["title"] == "The Matrix"
    assert body["release_date"] == "1999-03-31"
    assert len(body["genres"]) == 2
    genre_names = {g["name"] for g in body["genres"]}
    assert genre_names == {"Action", "Sci-Fi"}
    assert body["rating_internal"] is None
    assert body["rating_count_internal"] == 0


async def test_get_movie_returns_404(client, db):
    """GET /movies/{slug} returns 404 when not in DB and TMDB also has nothing."""
    with (
        patch.object(service._tmdb, "search_movie", new_callable=AsyncMock, return_value=None),
    ):
        response = await client.get("/v1/movies/nonexistent-slug-404-test")

    assert response.status_code == 404


async def test_get_movie_credits_empty(client, db):
    """GET /movies/{slug} returns credits as [] when no credits exist."""
    await repo.upsert_movie(db, _make_movie_dict("credits-empty-movie-1999"))

    response = await client.get("/v1/movies/credits-empty-movie-1999")
    assert response.status_code == 200

    body = response.json()
    assert "credits" in body
    assert body["credits"] == []


async def test_get_movie_credits_merge_cast_and_crew_in_order(client, db):
    """GET /movies/{slug} merges ``item_cast`` and ``credits`` (feature 89).

    The endpoint contract did not change when the storage did: the cast comes
    first, in billing order, then the crew — exactly what the single
    ``ORDER BY billing_order ASC NULLS LAST`` used to produce.  ``apps/web``
    renders this array verbatim, so the shape is a contract too.
    """
    movie = await repo.upsert_movie(db, _make_movie_dict("credits-ordered-movie-1999"))
    now = datetime.now(UTC)

    director = await people_repo.upsert_person(
        db,
        {
            "name": "Director A",
            "slug": "director-a-credits-movie-test",
            "profile_url": "https://example.com/a.jpg",
            "last_synced_at": now,
        },
    )
    await people_repo.upsert_credit(
        db,
        {
            "item_type": "MOVIE",
            "item_id": movie.id,
            "person_id": director.id,
            "role": "DIRECTOR",
        },
    )
    # Deliberately out of billing order: ``build_cast_payload`` sorts.
    await upsert_item_cast(
        db,
        "MOVIE",
        [(movie.id, build_cast_payload([("Actor B", "Bob", 2), ("Actor A", "Alice", 1)]))],
    )

    response = await client.get("/v1/movies/credits-ordered-movie-1999")
    assert response.status_code == 200

    body = response.json()
    credits = body["credits"]
    assert len(credits) == 3
    assert credits[0]["person_name"] == "Actor A"
    assert credits[0]["role"] == "ACTOR"
    assert credits[0]["character_name"] == "Alice"
    assert credits[0]["billing_order"] == 1
    assert credits[0]["person_slug"] == "actor-a"
    # The cast has no ``people`` row any more, so no photo travels with it.
    assert credits[0]["profile_url"] is None
    assert credits[1]["person_name"] == "Actor B"
    assert credits[1]["billing_order"] == 2
    # Crew last, with the ``people`` row behind it intact.
    assert credits[2]["person_name"] == "Director A"
    assert credits[2]["role"] == "DIRECTOR"
    assert credits[2]["profile_url"] == "https://example.com/a.jpg"
    assert credits[2]["character_name"] is None
    assert credits[2]["billing_order"] is None
