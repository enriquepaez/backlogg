import re

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import repository as repo
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.models import Book
from backlogg.shared.external_ids import upsert_external_id

_ol_client = OpenLibraryClient()


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-1999``) and replaces hyphens
    with spaces so the string can be used as an Open Library search query.
    """
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


async def get_book(db: AsyncSession, slug: str) -> Book:
    # 1. Look up in local DB
    book = await repo.get_book_by_slug(db, slug)
    if book:
        return book

    # 2. Derive a search title from the slug and query Open Library
    query = _title_from_slug(slug)
    search_result = await _ol_client.search_book(query)
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
    await db.commit()

    return book
