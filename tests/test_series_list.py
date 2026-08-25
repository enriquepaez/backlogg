"""Tests for GET /series list endpoint (feature 14)."""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.series import repository as repo


def _make_series(
    slug: str,
    title: str,
    rating: float | None,
    first_air_date: date | None,
    genres: list[dict],
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "Test series overview.",
        "first_air_date": first_air_date,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": rating,
        "rating_count_external": 500 if rating else None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
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


async def test_list_series_returns_200_empty(client, db):
    """GET /series returns 200 with pagination metadata."""
    response = await client.get("/v1/series")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body


async def test_list_series_response_fields(client, db):
    """GET /series items include required fields; release_date maps from first_air_date."""
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-fields-2018",
            title="Series Fields Test",
            rating=7.2,
            first_air_date=date(2018, 4, 22),
            genres=[{"name": "sr-fields-scifi-name", "slug": "sr-fields-scifi-slug"}],
        ),
    )

    response = await client.get("/v1/series?genre=sr-fields-scifi-slug")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] > 0
    assert item["title"] == "Series Fields Test"
    assert item["slug"] == "sr-fields-2018"
    assert item["poster_url"] is not None
    assert item["release_date"] == "2018-04-22"  # maps from first_air_date
    assert item["rating_external"] == 7.2
    assert isinstance(item["genres"], list)
    assert "sr-fields-scifi-slug" in item["genres"]


async def test_list_series_filter_by_genre(client, db):
    """GET /series?genre=slug returns only series with that genre."""
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-crime-2006",
            title="Crime Series",
            rating=8.0,
            first_air_date=date(2006, 3, 3),
            genres=[{"name": "sr-crime-genre-name", "slug": "sr-crime-genre-slug"}],
        ),
    )
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-comedy-2007",
            title="Comedy Series",
            rating=7.0,
            first_air_date=date(2007, 3, 3),
            genres=[{"name": "sr-comedy-genre-name", "slug": "sr-comedy-genre-slug"}],
        ),
    )

    response = await client.get("/v1/series?genre=sr-crime-genre-slug")
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert "sr-crime-2006" in slugs
    assert "sr-comedy-2007" not in slugs
    assert body["total"] == 1


async def test_list_series_response_includes_rating_internal(client, db):
    """GET /series items include rating_internal — with a value and with null (feature 69)."""
    genre = {"name": "sr-rating-internal-name", "slug": "sr-rating-internal-slug"}
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-rating-internal-set-2021",
            title="Series With Internal Rating",
            rating=7.0,
            first_air_date=date(2021, 1, 1),
            genres=[genre],
        )
        | {"rating_internal": 3.75},
    )
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-rating-internal-null-2021",
            title="Series Without Internal Rating",
            rating=6.0,
            first_air_date=date(2021, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/series?genre=sr-rating-internal-slug")
    assert response.status_code == 200
    body = response.json()
    by_slug = {item["slug"]: item for item in body["items"]}
    assert by_slug["sr-rating-internal-set-2021"]["rating_internal"] == 3.75
    assert by_slug["sr-rating-internal-null-2021"]["rating_internal"] is None


async def test_list_series_sort_date_desc_uses_first_air_date(client, db):
    """GET /series?sort=date_desc sorts by first_air_date descending."""
    genre = {"name": "sr-date-genre-name", "slug": "sr-date-genre-slug"}
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-old-air-1995",
            title="Old Air Series",
            rating=7.0,
            first_air_date=date(1995, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-new-air-2021",
            title="New Air Series",
            rating=7.0,
            first_air_date=date(2021, 11, 11),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/series?sort=date_desc&genre=sr-date-genre-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    new_idx = next(i for i, item in enumerate(items) if item["slug"] == "sr-new-air-2021")
    old_idx = next(i for i, item in enumerate(items) if item["slug"] == "sr-old-air-1995")
    assert new_idx < old_idx


async def test_list_series_sort_rating_desc(client, db):
    """GET /series?sort=rating_desc orders by rating_external descending."""
    genre = {"name": "sr-rating-genre-name", "slug": "sr-rating-genre-slug"}
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-rating-low-2019",
            title="Low Rating Series",
            rating=5.0,
            first_air_date=date(2019, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-rating-high-2019",
            title="High Rating Series",
            rating=9.5,
            first_air_date=date(2019, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/series?sort=rating_desc&genre=sr-rating-genre-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    high_idx = next(i for i, item in enumerate(items) if item["slug"] == "sr-rating-high-2019")
    low_idx = next(i for i, item in enumerate(items) if item["slug"] == "sr-rating-low-2019")
    assert high_idx < low_idx


async def test_list_series_pagination(client, db):
    """GET /series?page=2&limit=1 paginates correctly."""
    genre = {"name": "sr-page-genre-name", "slug": "sr-page-genre-slug"}
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-page-one-2019",
            title="Page One Series",
            rating=9.9,
            first_air_date=date(2019, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_series(
        db,
        _make_series(
            slug="sr-page-two-2019",
            title="Page Two Series",
            rating=9.8,
            first_air_date=date(2019, 1, 1),
            genres=[genre],
        ),
    )

    r1 = await client.get("/v1/series?sort=rating_desc&page=1&limit=1&genre=sr-page-genre-slug")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["items"]) == 1
    assert b1["total"] == 2

    r2 = await client.get("/v1/series?sort=rating_desc&page=2&limit=1&genre=sr-page-genre-slug")
    assert r2.status_code == 200
    b2 = r2.json()
    assert len(b2["items"]) == 1
    assert b2["page"] == 2
    assert b1["items"][0]["slug"] != b2["items"][0]["slug"]
