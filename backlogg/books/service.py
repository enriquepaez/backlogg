import logging
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import repository as repo
from backlogg.books.adapters.open_library import OpenLibraryClient, _slugify
from backlogg.books.models import Book
from backlogg.books.schemas import (
    BookGenreOut,
    BookListItemOut,
    BookListOut,
    BookOut,
    BookSortEnum,
    SimilarBookOut,
    SimilarBooksOut,
)
from backlogg.library import service as library_service
from backlogg.people import repository as people_repo
from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import upsert_external_id
from backlogg.shared.models import Person
from backlogg.shared.schemas import CreditOut

_ol_client = OpenLibraryClient()

logger = logging.getLogger(__name__)


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-1999``) and replaces hyphens
    with spaces so the string can be used as an Open Library search query.
    """
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


async def _get_or_create_person_ol(
    db: AsyncSession,
    ol_id: str,
    name: str,
    slug: str,
    now: datetime,
) -> Person | None:
    """Look up a person by Open Library ID; create one if not found.

    Returns the Person instance, or None if the lookup/creation fails.
    Avoids IntegrityError on uq_external_id when the same OL author
    appears in multiple books with slightly different name variants.
    """
    existing_id = await people_repo.get_person_id_by_external(db, "OPEN_LIBRARY", ol_id)
    if existing_id is not None:
        return await people_repo.get_person_by_id(db, existing_id)

    person = await people_repo.upsert_person(
        db,
        {
            "name": name,
            "slug": slug,
            "profile_url": None,
            "last_synced_at": now,
        },
    )
    await upsert_external_id(db, "PERSON", person.id, "OPEN_LIBRARY", ol_id)
    return person


async def _persist_book_authors(db: AsyncSession, book: Book, work_detail: dict) -> None:
    """Fetch authors from Open Library and persist them as people + credits."""
    authors = work_detail.get("authors", [])
    now = datetime.now(UTC)

    for entry in authors:
        try:
            author_key = entry.get("author", {}).get("key", "")
            if not author_key:
                continue
            author_id = author_key.removeprefix("/authors/")

            author_data = await _ol_client.get_author(author_id)
            if not author_data:
                continue

            name = author_data.get("name") or author_data.get("personal_name")
            if not name:
                continue

            slug = _slugify(name)

            person = await _get_or_create_person_ol(db, author_id, name, slug, now)
            if person is None:
                continue

            await people_repo.upsert_credit(
                db,
                {
                    "item_type": "BOOK",
                    "item_id": book.id,
                    "person_id": person.id,
                    "role": "AUTHOR",
                    "character_name": None,
                    "billing_order": None,
                },
            )
        except Exception:
            logger.exception("_persist_book_authors: error for entry=%s", entry)
            # Graceful degradation: continue with next author


async def list_books(
    db: AsyncSession,
    genre: str | None,
    sort: BookSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters,
) -> BookListOut:
    items, total = await repo.list_books(
        db, genre=genre, sort=sort, page=page, limit=limit, filters=filters
    )
    list_items = [
        BookListItemOut(
            id=b.id,
            title=b.title,
            slug=b.slug,
            poster_url=b.poster_url,
            release_date=b.first_publish_date,
            rating_external=float(b.rating_external) if b.rating_external is not None else None,
            genres=[g.slug for g in b.genres],
        )
        for b in items
    ]
    return BookListOut(items=list_items, total=total, page=page, limit=limit)


def _book_to_out(book: Book, credits: list[CreditOut], viewer_status: str | None) -> BookOut:
    return BookOut(
        id=book.id,
        title=book.title,
        original_title=book.original_title,
        slug=book.slug,
        overview=book.overview,
        first_publish_date=book.first_publish_date,
        original_language=book.original_language,
        poster_url=book.poster_url,
        rating_external=float(book.rating_external) if book.rating_external is not None else None,
        rating_count_external=book.rating_count_external,
        rating_internal=(float(book.rating_internal) if book.rating_internal is not None else None),
        rating_count_internal=book.rating_count_internal,
        genres=[BookGenreOut(id=g.id, name=g.name, slug=g.slug) for g in book.genres],
        credits=credits,
        viewer_status=viewer_status,
    )


async def get_book(db: AsyncSession, slug: str, viewer_id: int | None = None) -> BookOut:
    # 1. Look up in local DB
    book = await repo.get_book_by_slug(db, slug)
    if book is None:
        # 2. Derive a search title from the slug and query Open Library
        query = _title_from_slug(slug)
        search_results = await _ol_client.search_book(query)
        search_result = search_results[0] if search_results else None
        if search_result is None:
            raise HTTPException(status_code=404, detail="Book not found")

        # 3. Optionally fetch full work detail for synopsis
        # work_key is like "/works/OL123W" — strip the prefix to get the bare OLID
        work_key = search_result.get("key", "")  # e.g. "/works/OL123W"
        work_id = work_key.removeprefix("/works/") if work_key else None
        work_detail: dict | None = None
        if work_id:
            work_detail = await _ol_client.get_work_detail(work_id)

        # 4. Convert to DB-ready dict and persist
        book_data = _ol_client.book_to_dict(search_result, work_detail)
        book = await repo.upsert_book(db, book_data)

        # 5. Persist the Open Library external ID
        if work_id:
            await upsert_external_id(db, "BOOK", book.id, "OPEN_LIBRARY", work_id)

        # 6. Persist authors as people + credits
        if work_detail:
            await _persist_book_authors(db, book, work_detail)

        await db.commit()

    credits = await get_credits_for_item(db, "BOOK", book.id)
    viewer_status = await library_service.get_viewer_status(db, "BOOK", book.id, viewer_id)
    return _book_to_out(book, credits, viewer_status)


_MAX_SIMILAR_RESULTS = 10


def _book_to_similar_out(book: Book) -> SimilarBookOut:
    return SimilarBookOut(
        title=book.title,
        slug=book.slug,
        poster_url=book.poster_url,
        release_date=book.first_publish_date,
        rating_external=float(book.rating_external) if book.rating_external is not None else None,
    )


async def get_similar_books(db: AsyncSession, slug: str) -> SimilarBooksOut:
    """Up to 10 similar books, computed 100% locally (no external API calls).

    Priority tiers (feature 46):
    1. Books sharing an author with the source book (via people/credits,
       role=AUTHOR — feature 19), ordered by rating_external descending.
    2. Books sharing a genre with the source book, ordered by number of
       shared genres descending, then rating_external descending.
    The source book never appears in its own results.
    """
    book = await repo.get_book_by_slug(db, slug)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    results: list[SimilarBookOut] = []
    excluded_ids: set[int] = {book.id}

    author_ids = await repo.get_author_person_ids(db, book.id)
    if author_ids:
        author_books = await repo.get_books_by_same_authors(
            db, author_ids, book.id, limit=_MAX_SIMILAR_RESULTS
        )
        for candidate in author_books:
            if candidate.id in excluded_ids:
                continue
            excluded_ids.add(candidate.id)
            results.append(_book_to_similar_out(candidate))

    if len(results) < _MAX_SIMILAR_RESULTS:
        genre_ids = [g.id for g in book.genres]
        if genre_ids:
            genre_books = await repo.get_books_by_genre_overlap(
                db,
                book.id,
                genre_ids,
                excluded_ids,
                limit=_MAX_SIMILAR_RESULTS - len(results),
            )
            for candidate in genre_books:
                if candidate.id in excluded_ids:
                    continue
                excluded_ids.add(candidate.id)
                results.append(_book_to_similar_out(candidate))

    return SimilarBooksOut(results=results[:_MAX_SIMILAR_RESULTS])
