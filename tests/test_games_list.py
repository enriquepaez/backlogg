"""Tests for GET /games list endpoint (feature 14)."""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.games import repository as repo
from backlogg.main import app


def _make_game(
    slug: str,
    title: str,
    rating: float | None,
    release_date: date | None,
    genres: list[dict],
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "Test game overview.",
        "release_date": release_date,
        "game_type": "main_game",
        "original_language": None,
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": rating,
        "rating_count_external": 1000 if rating else None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
        "platforms": [],
        "companies": [],
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


async def test_list_games_returns_200_empty(client, db):
    """GET /games returns 200 with pagination metadata."""
    response = await client.get("/games")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body


async def test_list_games_response_fields(client, db):
    """GET /games items include all required fields."""
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-fields-2023",
            title="Game Fields Test",
            rating=8.5,
            release_date=date(2023, 2, 10),
            genres=[{"name": "gm-fields-rpg-name", "slug": "gm-fields-rpg-slug"}],
        ),
    )

    response = await client.get("/games?genre=gm-fields-rpg-slug")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] > 0
    assert item["title"] == "Game Fields Test"
    assert item["slug"] == "gm-fields-2023"
    assert item["poster_url"] is not None
    assert item["release_date"] == "2023-02-10"
    assert item["rating_external"] == 8.5
    assert isinstance(item["genres"], list)
    assert "gm-fields-rpg-slug" in item["genres"]


async def test_list_games_filter_by_genre(client, db):
    """GET /games?genre=slug returns only games with that genre."""
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-fps-2016",
            title="FPS Game",
            rating=8.0,
            release_date=date(2016, 5, 13),
            genres=[{"name": "gm-fps-genre-name", "slug": "gm-fps-genre-slug"}],
        ),
    )
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-puzzle-2017",
            title="Puzzle Game",
            rating=7.5,
            release_date=date(2017, 8, 8),
            genres=[{"name": "gm-puzzle-genre-name", "slug": "gm-puzzle-genre-slug"}],
        ),
    )

    response = await client.get("/games?genre=gm-fps-genre-slug")
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert "gm-fps-2016" in slugs
    assert "gm-puzzle-2017" not in slugs
    assert body["total"] == 1


async def test_list_games_sort_rating_desc(client, db):
    """GET /games?sort=rating_desc orders by rating_external descending."""
    genre = {"name": "gm-sort-rating-name", "slug": "gm-sort-rating-slug"}
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-sort-low-2010",
            title="Low Rating Game",
            rating=4.0,
            release_date=date(2010, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-sort-high-2010",
            title="High Rating Game",
            rating=9.8,
            release_date=date(2010, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/games?sort=rating_desc&genre=gm-sort-rating-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    high_idx = next(i for i, item in enumerate(items) if item["slug"] == "gm-sort-high-2010")
    low_idx = next(i for i, item in enumerate(items) if item["slug"] == "gm-sort-low-2010")
    assert high_idx < low_idx


async def test_list_games_sort_date_desc(client, db):
    """GET /games?sort=date_desc orders by release_date descending."""
    genre = {"name": "gm-date-genre-name", "slug": "gm-date-genre-slug"}
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-old-1993",
            title="Old Game",
            rating=7.0,
            release_date=date(1993, 9, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-new-2022",
            title="New Game",
            rating=7.0,
            release_date=date(2022, 11, 9),
            genres=[genre],
        ),
    )

    response = await client.get("/games?sort=date_desc&genre=gm-date-genre-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    new_idx = next(i for i, item in enumerate(items) if item["slug"] == "gm-new-2022")
    old_idx = next(i for i, item in enumerate(items) if item["slug"] == "gm-old-1993")
    assert new_idx < old_idx


async def test_list_games_pagination(client, db):
    """GET /games?page=2&limit=1 paginates correctly."""
    genre = {"name": "gm-page-genre-name", "slug": "gm-page-genre-slug"}
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-page-a-2024",
            title="Page A Game",
            rating=9.9,
            release_date=date(2024, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_game(
        db,
        _make_game(
            slug="gm-page-b-2024",
            title="Page B Game",
            rating=9.7,
            release_date=date(2024, 1, 1),
            genres=[genre],
        ),
    )

    r1 = await client.get("/games?sort=rating_desc&page=1&limit=1&genre=gm-page-genre-slug")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["items"]) == 1
    assert b1["total"] == 2

    r2 = await client.get("/games?sort=rating_desc&page=2&limit=1&genre=gm-page-genre-slug")
    assert r2.status_code == 200
    b2 = r2.json()
    assert len(b2["items"]) == 1
    assert b2["page"] == 2
    assert b1["items"][0]["slug"] != b2["items"][0]["slug"]
