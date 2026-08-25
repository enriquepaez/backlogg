"""Tests for GET /movies list endpoint (feature 14)."""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app
from backlogg.movies import repository as repo


def _make_movie(
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
        "overview": "Test overview.",
        "release_date": release_date,
        "runtime": 120,
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rating,
        "rating_count_external": 1000 if rating else None,
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


async def test_list_movies_returns_200_empty(client, db):
    """GET /movies returns 200 with pagination metadata."""
    response = await client.get("/v1/movies")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    assert body["page"] == 1
    assert body["limit"] == 20


async def test_list_movies_response_fields(client, db):
    """GET /movies items include all required fields."""
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-fields-check-2020",
            title="Movie Fields Check",
            rating=6.5,
            release_date=date(2020, 3, 10),
            genres=[{"name": "mv-fields-comedy-name", "slug": "mv-fields-comedy-slug"}],
        ),
    )

    response = await client.get("/v1/movies?genre=mv-fields-comedy-slug")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] > 0
    assert item["title"] == "Movie Fields Check"
    assert item["slug"] == "mv-fields-check-2020"
    assert item["poster_url"] is not None
    assert item["release_date"] == "2020-03-10"
    assert item["rating_external"] == 6.5
    assert isinstance(item["genres"], list)
    assert "mv-fields-comedy-slug" in item["genres"]
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["limit"] == 20


async def test_list_movies_filter_by_genre(client, db):
    """GET /movies?genre=slug returns only movies with that genre."""
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-genre-sci-2010",
            title="Sci-Fi Movie",
            rating=7.0,
            release_date=date(2010, 5, 5),
            genres=[{"name": "mv-scifi-filter-name", "slug": "mv-scifi-filter-slug"}],
        ),
    )
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-genre-action-2010",
            title="Action Movie",
            rating=7.0,
            release_date=date(2010, 5, 5),
            genres=[{"name": "mv-action-filter-name", "slug": "mv-action-filter-slug"}],
        ),
    )

    response = await client.get("/v1/movies?genre=mv-scifi-filter-slug")
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert "mv-genre-sci-2010" in slugs
    assert "mv-genre-action-2010" not in slugs
    assert body["total"] == 1


async def test_list_movies_sort_rating_desc(client, db):
    """GET /movies?sort=rating_desc orders by rating_external descending."""
    genre = {"name": "mv-sort-rating-name", "slug": "mv-sort-rating-slug"}
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-sort-low-2015",
            title="Low Rating Movie",
            rating=5.0,
            release_date=date(2015, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-sort-high-2015",
            title="High Rating Movie",
            rating=9.0,
            release_date=date(2015, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/movies?sort=rating_desc&genre=mv-sort-rating-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    # High-rated should come before low-rated
    high_idx = next(i for i, item in enumerate(items) if item["slug"] == "mv-sort-high-2015")
    low_idx = next(i for i, item in enumerate(items) if item["slug"] == "mv-sort-low-2015")
    assert high_idx < low_idx


async def test_list_movies_sort_date_desc(client, db):
    """GET /movies?sort=date_desc orders by release_date descending."""
    genre = {"name": "mv-sort-date-name", "slug": "mv-sort-date-slug"}
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-date-old-1990",
            title="Old Movie",
            rating=7.0,
            release_date=date(1990, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-date-new-2022",
            title="New Movie",
            rating=7.0,
            release_date=date(2022, 12, 31),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/movies?sort=date_desc&genre=mv-sort-date-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    new_idx = next(i for i, item in enumerate(items) if item["slug"] == "mv-date-new-2022")
    old_idx = next(i for i, item in enumerate(items) if item["slug"] == "mv-date-old-1990")
    assert new_idx < old_idx


async def test_list_movies_response_includes_rating_internal(client, db):
    """GET /movies items include rating_internal — with a value and with null (feature 69)."""
    genre = {"name": "mv-rating-internal-name", "slug": "mv-rating-internal-slug"}
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-rating-internal-set-2021",
            title="Movie With Internal Rating",
            rating=7.0,
            release_date=date(2021, 1, 1),
            genres=[genre],
        )
        | {"rating_internal": 4.25},
    )
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-rating-internal-null-2021",
            title="Movie Without Internal Rating",
            rating=6.0,
            release_date=date(2021, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/movies?genre=mv-rating-internal-slug")
    assert response.status_code == 200
    body = response.json()
    by_slug = {item["slug"]: item for item in body["items"]}
    assert "rating_internal" in by_slug["mv-rating-internal-set-2021"]
    assert by_slug["mv-rating-internal-set-2021"]["rating_internal"] == 4.25
    assert by_slug["mv-rating-internal-null-2021"]["rating_internal"] is None


async def test_list_movies_pagination(client, db):
    """GET /movies?page=2&limit=1 paginates correctly."""
    genre = {"name": "mv-page-genre-name", "slug": "mv-page-genre-slug"}
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-page-alpha-2005",
            title="Alpha Movie",
            rating=9.5,
            release_date=date(2005, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_movie(
        db,
        _make_movie(
            slug="mv-page-beta-2005",
            title="Beta Movie",
            rating=9.4,
            release_date=date(2005, 1, 1),
            genres=[genre],
        ),
    )

    r1 = await client.get("/v1/movies?sort=rating_desc&page=1&limit=1&genre=mv-page-genre-slug")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["items"]) == 1
    assert b1["page"] == 1
    assert b1["limit"] == 1
    assert b1["total"] == 2

    r2 = await client.get("/v1/movies?sort=rating_desc&page=2&limit=1&genre=mv-page-genre-slug")
    assert r2.status_code == 200
    b2 = r2.json()
    assert len(b2["items"]) == 1
    assert b2["page"] == 2
    assert b1["items"][0]["slug"] != b2["items"][0]["slug"]
