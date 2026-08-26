from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.books import repository as repo
from backlogg.books import service


def _make_search_doc() -> dict:
    return {
        "key": "/works/OL123W",
        "title": "Dune",
        "author_name": ["Frank Herbert"],
        "first_publish_year": 1965,
        "cover_i": 9988776,
        "subject": ["Science Fiction", "Epic", "Space opera"],
        "isbn": ["9780441013593"],
    }


def _make_work_detail() -> dict:
    return {
        "key": "/works/OL123W",
        "title": "Dune",
        "description": {"type": "/type/text", "value": "A science fiction epic."},
        "first_publish_date": "1965",
    }


def _make_book_dict() -> dict:
    return {
        "title": "Dune",
        "original_title": None,
        "slug": "dune-1965",
        "overview": "A science fiction epic.",
        "first_publish_date": date(1965, 1, 1),
        "original_language": None,
        "poster_url": "https://covers.openlibrary.org/b/id/9988776-L.jpg",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Science Fiction", "slug": "science-fiction"},
            {"name": "Epic", "slug": "epic"},
        ],
    }


async def test_get_book_found_in_db(db):
    """When book exists in DB, service returns it without calling Open Library."""
    await repo.upsert_book(db, _make_book_dict())

    with patch.object(service._ol_client, "search_book", new_callable=AsyncMock) as mock_search:
        result = await service.get_book(db, "dune-1965")

    assert result.slug == "dune-1965"
    mock_search.assert_not_called()


async def test_get_book_fallback_to_open_library(db):
    """When book is not in DB, service calls Open Library, persists and returns it."""
    search_doc = _make_search_doc()
    work_detail = _make_work_detail()

    with (
        patch.object(
            service._ol_client,
            "search_book",
            new_callable=AsyncMock,
            return_value=[search_doc],
        ),
        patch.object(
            service._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=work_detail,
        ),
    ):
        result = await service.get_book(db, "dune-1965")

    assert result.title == "Dune"
    assert result.slug == "dune-1965"
    # search_doc carries isbn (feature 71) — book_to_dict maps it through
    assert result.isbn == "9780441013593"

    # Verify persisted in DB
    persisted = await repo.get_book_by_slug(db, "dune-1965")
    assert persisted is not None
    assert persisted.isbn == "9780441013593"


async def test_get_book_fallback_without_isbn(db):
    """A search_doc with no isbn must persist and expose isbn=None, not break the flow."""
    search_doc = _make_search_doc()
    search_doc["key"] = "/works/OL999W"
    search_doc["title"] = "Dune Messiah"  # distinct slug from the isbn-present test above
    del search_doc["isbn"]
    work_detail = _make_work_detail()
    work_detail["key"] = "/works/OL999W"
    work_detail["title"] = "Dune Messiah"

    with (
        patch.object(
            service._ol_client,
            "search_book",
            new_callable=AsyncMock,
            return_value=[search_doc],
        ),
        patch.object(
            service._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=work_detail,
        ),
    ):
        result = await service.get_book(db, "dune-messiah-1965")

    assert result.isbn is None

    persisted = await repo.get_book_by_slug(db, "dune-messiah-1965")
    assert persisted is not None
    assert persisted.isbn is None


async def test_get_book_not_found_anywhere(db):
    """When Open Library returns None, service raises HTTP 404."""
    with patch.object(service._ol_client, "search_book", new_callable=AsyncMock, return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_book(db, "this-slug-does-not-exist-9999")

    assert exc_info.value.status_code == 404
