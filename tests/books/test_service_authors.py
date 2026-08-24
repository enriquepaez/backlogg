"""Tests for book author persistence in backlogg/books/service.py.

Most tests call _persist_book_authors directly to avoid coupling to
service.get_book's commit/session semantics (which make mocks fragile
on test reruns since committed data persists between runs).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from backlogg.books import repository as books_repo
from backlogg.books import service
from backlogg.books.service import _persist_book_authors
from backlogg.people.repository import get_person_by_slug
from backlogg.shared.external_ids import get_external_id

# Unique synthetic OL IDs per test. Long format to never appear in real OL data.
# Suffixes T1–T5 map to the corresponding test.
_F19_T1_WORK = "OLF19T1WORK001W"
_F19_T1_AUTHOR = "OLF19T1AUTH001A"
_F19_T2_AUTHOR = "OLF19T2AUTH001A"
_F19_T3_AUTHOR = "OLF19T3AUTH001A"
_F19_T4_WORK = "OLF19T4WORK001W"
_F19_T5_WORK = "OLF19T5WORK001W"
_F19_T5_AUTHOR = "OLF19T5AUTH001A"


def _make_book_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": None,
        "first_publish_date": None,
        "original_language": None,
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _make_work_detail(work_key: str, title: str, author_olid: str) -> dict:
    return {
        "key": work_key,
        "title": title,
        "description": "A test book.",
        "authors": [{"author": {"key": f"/authors/{author_olid}"}}],
    }


async def test_persist_book_authors_creates_person_and_credit(db):
    """_persist_book_authors creates a person in people and a credit with role=AUTHOR."""
    book = await books_repo.upsert_book(db, _make_book_data("f19-t1-test-book-001", "F19 T1 Book"))
    work_detail = _make_work_detail(f"/works/{_F19_T1_WORK}", "F19 T1 Book", _F19_T1_AUTHOR)
    author_data = {
        "key": f"/authors/{_F19_T1_AUTHOR}",
        "name": "F19 T1 Author Name",
        "personal_name": "F19 T1 Author Full Name",
    }

    with patch.object(
        service._ol_client,
        "get_author",
        new_callable=AsyncMock,
        return_value=author_data,
    ):
        await _persist_book_authors(db, book, work_detail)

    # Verify author is persisted in people
    person = await get_person_by_slug(db, "f19-t1-author-name")
    assert person is not None
    assert person.name == "F19 T1 Author Name"

    # Verify credit for this book with role=AUTHOR
    credits_for_book = [c for c in person.credits if c.item_id == book.id]
    assert len(credits_for_book) == 1
    credit = credits_for_book[0]
    assert credit.item_type == "BOOK"
    assert credit.role == "AUTHOR"

    # Verify external_id registered for the author
    ext_id = await get_external_id(db, "PERSON", person.id, "OPEN_LIBRARY")
    assert ext_id is not None
    assert ext_id.external_id == _F19_T1_AUTHOR


async def test_persist_book_authors_graceful_on_api_failure(db):
    """If get_author raises, the error is swallowed and remaining authors are skipped."""
    book = await books_repo.upsert_book(db, _make_book_data("f19-t2-test-book-001", "F19 T2 Book"))
    work_detail = _make_work_detail(f"/works/{_F19_T1_WORK}", "F19 T2 Book", _F19_T2_AUTHOR)
    mock_get_author = AsyncMock(side_effect=Exception("OL author API down"))

    with patch.object(service._ol_client, "get_author", new=mock_get_author):
        # Must NOT raise — graceful degradation
        await _persist_book_authors(db, book, work_detail)

    # get_author was called once
    mock_get_author.assert_called_once_with(_F19_T2_AUTHOR)

    # No person persisted because get_author raised
    person = await get_person_by_slug(db, "f19-t2-unique-never-created")
    assert person is None


async def test_persist_book_authors_skips_author_when_404(db):
    """If get_author returns None (404), the author is silently skipped."""
    book = await books_repo.upsert_book(db, _make_book_data("f19-t3-test-book-001", "F19 T3 Book"))
    work_detail = _make_work_detail(f"/works/{_F19_T1_WORK}", "F19 T3 Book", _F19_T3_AUTHOR)
    mock_get_author = AsyncMock(return_value=None)

    with patch.object(service._ol_client, "get_author", new=mock_get_author):
        await _persist_book_authors(db, book, work_detail)

    mock_get_author.assert_called_once_with(_F19_T3_AUTHOR)

    # No person created
    person = await get_person_by_slug(db, "f19-t3-unique-never-created")
    assert person is None


async def test_persist_book_authors_skips_when_no_authors(db):
    """If work_detail has an empty authors list, get_author is never called."""
    book = await books_repo.upsert_book(db, _make_book_data("f19-t4-test-book-001", "F19 T4 Book"))
    work_detail = {
        "key": f"/works/{_F19_T4_WORK}",
        "title": "F19 T4 Book",
        "authors": [],
    }

    with patch.object(
        service._ol_client,
        "get_author",
        new_callable=AsyncMock,
    ) as mock_get_author:
        await _persist_book_authors(db, book, work_detail)

    mock_get_author.assert_not_called()


async def test_persist_book_authors_idempotent(db):
    """Calling _persist_book_authors twice for the same book creates only 1 credit."""
    book = await books_repo.upsert_book(db, _make_book_data("f19-t5-test-book-001", "F19 T5 Book"))
    work_detail = _make_work_detail(f"/works/{_F19_T5_WORK}", "F19 T5 Book", _F19_T5_AUTHOR)
    author_data = {
        "key": f"/authors/{_F19_T5_AUTHOR}",
        "name": "F19 T5 Idempotent Author",
        "personal_name": "F19 T5 Idempotent Author Full",
    }

    with patch.object(
        service._ol_client,
        "get_author",
        new_callable=AsyncMock,
        return_value=author_data,
    ):
        await _persist_book_authors(db, book, work_detail)
        await _persist_book_authors(db, book, work_detail)

    person = await get_person_by_slug(db, "f19-t5-idempotent-author")
    assert person is not None
    assert person.name == "F19 T5 Idempotent Author"

    # Exactly 1 credit for this book despite being called twice
    credits_for_book = [c for c in person.credits if c.item_id == book.id]
    assert len(credits_for_book) == 1
    credit = credits_for_book[0]
    assert credit.item_type == "BOOK"
    assert credit.role == "AUTHOR"


async def test_get_book_calls_author_persistence(db):
    """service.get_book calls _persist_book_authors when work_detail is available.

    We force the fallback path by mocking get_book_by_slug to return None
    so the test is idempotent across reruns (avoids early-return when book is cached).
    """
    from unittest.mock import AsyncMock as AM

    search_doc = {
        "key": "/works/OLF19SVCTEST1W",
        "title": "F19 Service Integration Book",
        "first_publish_year": 1999,
        "cover_i": None,
        "subject": [],
        "isbn": [],
    }
    work_detail = {
        "key": "/works/OLF19SVCTEST1W",
        "title": "F19 Service Integration Book",
        "authors": [{"author": {"key": "/authors/OLF19SVCAUTH1A"}}],
    }

    with (
        patch("backlogg.books.service.repo.get_book_by_slug", new_callable=AM, return_value=None),
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
        patch("backlogg.books.service._persist_book_authors", new_callable=AM) as mock_persist,
    ):
        book = await service.get_book(db, "f19-service-integration-book-1999")

    assert book is not None
    mock_persist.assert_called_once()
    call_args = mock_persist.call_args
    # _persist_book_authors was called with (db, book, work_detail)
    assert call_args.args[2] == work_detail
