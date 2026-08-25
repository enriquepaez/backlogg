"""Library repository — DB queries for library_entries.

Only this file imports and uses SQLAlchemy for the library domain. It reuses
the ``ITEM_MODELS`` mapping and ``get_item_by_slug`` helper from
``backlogg/ratings/repository.py`` (polymorphic item_type/item_id lookups) and
builds the cross-type library listing with the same UNION ALL style as
``backlogg/feed/repository.py`` and ``backlogg/genres/repository.py`` — one
SELECT per item type joined to its content table, combined with ``union_all``.
"""

from typing import Any

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.library.models import LIBRARY_STATUSES, LibraryEntry
from backlogg.ratings.repository import ITEM_MODELS, get_item_by_slug

__all__ = [
    "get_item_by_slug",
    "get_library_entry",
    "get_library_status",
    "upsert_library_entry",
    "delete_library_entry",
    "list_user_library",
    "count_by_status",
]

# Content-type filter value (as sent in ?type=) -> stored item_type.
TYPE_FILTER_TO_ITEM_TYPE: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}

# release_date-equivalent column name per item type. Books use
# ``first_publish_date`` and series ``first_air_date`` as their release date.
_RELEASE_DATE_ATTR: dict[str, str] = {
    "MOVIE": "release_date",
    "SERIES": "first_air_date",
    "BOOK": "first_publish_date",
    "GAME": "release_date",
}


async def get_library_entry(
    db: AsyncSession, user_id: int, item_type: str, item_id: int
) -> LibraryEntry | None:
    result = await db.execute(
        select(LibraryEntry).where(
            LibraryEntry.user_id == user_id,
            LibraryEntry.item_type == item_type,
            LibraryEntry.item_id == item_id,
        )
    )
    return result.scalar_one_or_none()


async def get_library_status(
    db: AsyncSession, user_id: int, item_type: str, item_id: int
) -> str | None:
    """Return just the status string for the (user, item), or None."""
    result = await db.execute(
        select(LibraryEntry.status).where(
            LibraryEntry.user_id == user_id,
            LibraryEntry.item_type == item_type,
            LibraryEntry.item_id == item_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_library_entry(
    db: AsyncSession, user_id: int, item_type: str, item_id: int, status: str
) -> LibraryEntry:
    """Insert or update the (user, item) backlog status. Full replace of status."""
    stmt = (
        pg_insert(LibraryEntry)
        .values(user_id=user_id, item_type=item_type, item_id=item_id, status=status)
        .on_conflict_do_update(
            constraint="uq_library_entry_item",
            set_={"status": status},
        )
        .returning(LibraryEntry.id)
    )
    result = await db.execute(stmt)
    entry_id = result.scalar_one()
    await db.flush()

    # Expire any cached version so the SELECT below returns the fresh row (with
    # the trigger-updated ``updated_at``), not a stale identity-map entry —
    # same pattern as ratings.upsert_rating / movies.upsert_movie.
    for obj in db.identity_map.values():
        if isinstance(obj, LibraryEntry) and obj.id == entry_id:
            db.expire(obj)
            break

    row = await db.execute(select(LibraryEntry).where(LibraryEntry.id == entry_id))
    return row.scalar_one()


async def delete_library_entry(db: AsyncSession, entry: LibraryEntry) -> None:
    await db.delete(entry)
    await db.flush()


def _library_select(item_type: str, model: type):
    """Base SELECT for one item type: entry + joined content item fields."""
    release_col = getattr(model, _RELEASE_DATE_ATTR[item_type])
    return select(
        LibraryEntry.id.label("id"),
        literal(item_type, type_=String).label("item_type"),
        model.title.label("title"),
        model.slug.label("slug"),
        model.poster_url.label("poster_url"),
        release_col.label("release_date"),
        model.rating_external.label("rating_external"),
        model.rating_internal.label("rating_internal"),
        LibraryEntry.status.label("status"),
        LibraryEntry.created_at.label("created_at"),
        LibraryEntry.updated_at.label("updated_at"),
    ).join(model, LibraryEntry.item_id == model.id)


async def list_user_library(
    db: AsyncSession,
    user_id: int,
    status: str | None,
    item_type_filter: str | None,
    page: int,
    limit: int,
) -> tuple[list[Any], int]:
    """Cross-type UNION ALL of a user's library, newest first, paginated.

    Optional filters: ``status`` (want/in_progress/completed/dropped) and
    ``item_type_filter`` (MOVIE/SERIES/BOOK/GAME) — when the type filter is set
    only that content type is queried.
    """
    types = (
        {item_type_filter: ITEM_MODELS[item_type_filter]}
        if item_type_filter is not None
        else ITEM_MODELS
    )

    queries = []
    for item_type, model in types.items():
        q = _library_select(item_type, model).where(
            LibraryEntry.user_id == user_id,
            LibraryEntry.item_type == item_type,
        )
        if status is not None:
            q = q.where(LibraryEntry.status == status)
        queries.append(q)

    combined = union_all(*queries) if len(queries) > 1 else queries[0]
    union_subq = combined.subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(union_subq.c.created_at.desc(), union_subq.c.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total


async def count_by_status(db: AsyncSession, user_id: int) -> dict[str, int]:
    """Return per-status counts for a user's library, zero-filled for all statuses."""
    result = await db.execute(
        select(LibraryEntry.status, func.count())
        .where(LibraryEntry.user_id == user_id)
        .group_by(LibraryEntry.status)
    )
    counts = dict.fromkeys(LIBRARY_STATUSES, 0)
    for status, count in result.all():
        counts[status] = count
    return counts
