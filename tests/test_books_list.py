"""Tests for GET /books list endpoint (feature 14)."""

from datetime import UTC, date, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as repo
from backlogg.main import app


def _make_book(
    slug: str,
    title: str,
    rating: float | None,
    first_publish_date: date | None,
    genres: list[dict],
) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "Test book overview.",
        "first_publish_date": first_publish_date,
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "rating_external": rating,
        "rating_count_external": 200 if rating else None,
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


async def test_list_books_returns_200_empty(client, db):
    """GET /books returns 200 with pagination metadata."""
    response = await client.get("/v1/books")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body


async def test_list_books_response_fields(client, db):
    """GET /books items include required fields; release_date maps from first_publish_date."""
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-fields-1949",
            title="Book Fields Check",
            rating=4.8,
            first_publish_date=date(1949, 6, 8),
            genres=[{"name": "bk-fields-dystopian-name", "slug": "bk-fields-dystopian-slug"}],
        ),
    )

    response = await client.get("/v1/books?genre=bk-fields-dystopian-slug")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] > 0
    assert item["title"] == "Book Fields Check"
    assert item["slug"] == "bk-fields-1949"
    assert item["poster_url"] is not None
    assert item["release_date"] == "1949-06-08"  # maps from first_publish_date
    assert item["rating_external"] == 4.8
    assert isinstance(item["genres"], list)
    assert "bk-fields-dystopian-slug" in item["genres"]


async def test_list_books_filter_by_genre(client, db):
    """GET /books?genre=slug returns only books with that genre."""
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-mystery-2000",
            title="Mystery Book",
            rating=4.0,
            first_publish_date=date(2000, 1, 1),
            genres=[{"name": "bk-mystery-genre-name", "slug": "bk-mystery-genre-slug"}],
        ),
    )
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-romance-2001",
            title="Romance Book",
            rating=3.5,
            first_publish_date=date(2001, 2, 2),
            genres=[{"name": "bk-romance-genre-name", "slug": "bk-romance-genre-slug"}],
        ),
    )

    response = await client.get("/v1/books?genre=bk-mystery-genre-slug")
    assert response.status_code == 200
    body = response.json()
    slugs = [item["slug"] for item in body["items"]]
    assert "bk-mystery-2000" in slugs
    assert "bk-romance-2001" not in slugs
    assert body["total"] == 1


async def test_list_books_sort_date_desc_uses_first_publish_date(client, db):
    """GET /books?sort=date_desc sorts by first_publish_date descending."""
    genre = {"name": "bk-date-genre-name", "slug": "bk-date-genre-slug"}
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-old-1851",
            title="Old Published Book",
            rating=4.0,
            first_publish_date=date(1851, 10, 18),
            genres=[genre],
        ),
    )
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-new-2020",
            title="New Published Book",
            rating=4.0,
            first_publish_date=date(2020, 9, 15),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/books?sort=date_desc&genre=bk-date-genre-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    new_idx = next(i for i, item in enumerate(items) if item["slug"] == "bk-new-2020")
    old_idx = next(i for i, item in enumerate(items) if item["slug"] == "bk-old-1851")
    assert new_idx < old_idx


async def test_list_books_sort_rating_desc(client, db):
    """GET /books?sort=rating_desc orders by rating_external descending."""
    genre = {"name": "bk-rating-genre-name", "slug": "bk-rating-genre-slug"}
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-low-rating-2015",
            title="Low Rating Book",
            rating=2.5,
            first_publish_date=date(2015, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-high-rating-2015",
            title="High Rating Book",
            rating=5.0,
            first_publish_date=date(2015, 1, 1),
            genres=[genre],
        ),
    )

    response = await client.get("/v1/books?sort=rating_desc&genre=bk-rating-genre-slug")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) == 2
    high_idx = next(i for i, item in enumerate(items) if item["slug"] == "bk-high-rating-2015")
    low_idx = next(i for i, item in enumerate(items) if item["slug"] == "bk-low-rating-2015")
    assert high_idx < low_idx


async def test_list_books_pagination(client, db):
    """GET /books?page=2&limit=1 paginates correctly."""
    genre = {"name": "bk-page-genre-name", "slug": "bk-page-genre-slug"}
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-page-first-1920",
            title="Page First Book",
            rating=5.0,
            first_publish_date=date(1920, 1, 1),
            genres=[genre],
        ),
    )
    await repo.upsert_book(
        db,
        _make_book(
            slug="bk-page-second-1921",
            title="Page Second Book",
            rating=4.9,
            first_publish_date=date(1921, 1, 1),
            genres=[genre],
        ),
    )

    r1 = await client.get("/v1/books?sort=rating_desc&page=1&limit=1&genre=bk-page-genre-slug")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["items"]) == 1
    assert b1["total"] == 2

    r2 = await client.get("/v1/books?sort=rating_desc&page=2&limit=1&genre=bk-page-genre-slug")
    assert r2.status_code == 200
    b2 = r2.json()
    assert len(b2["items"]) == 1
    assert b2["page"] == 2
    assert b1["items"][0]["slug"] != b2["items"][0]["slug"]
