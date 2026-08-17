"""Library logs repository — DB queries for library_logs.

Only this file imports and uses SQLAlchemy for the library_logs domain. It
reuses the ``ITEM_MODELS`` mapping and ``get_item_by_slug`` helper from
``backlogg/ratings/repository.py`` (polymorphic item_type/item_id lookups) and
builds the cross-type user log listing with the same UNION ALL style as
``backlogg/library/repository.py`` and ``backlogg/ratings/repository.py`` —
one SELECT per item type joined to its content table, combined with
``union_all``. Unlike ``ratings``/``library``, creating a log is a plain
INSERT (never an upsert) — ``library_logs`` has no unique constraint on
``(user_id, item_type, item_id)``, so a user may have multiple logs for the
same item.
"""

from datetime import date
from typing import Any

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.library_logs.models import LibraryLog
from backlogg.ratings.repository import ITEM_MODELS, get_item_by_slug

__all__ = [
    "get_item_by_slug",
    "create_log",
    "get_log_by_id",
    "delete_log",
    "list_logs_for_item",
    "list_user_log",
]


async def create_log(
    db: AsyncSession,
    user_id: int,
    item_type: str,
    item_id: int,
    logged_on: date,
    rewatch: bool,
    note: str | None,
) -> LibraryLog:
    """Insert a new log row. Never an upsert — multiple logs per item allowed."""
    log = LibraryLog(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        logged_on=logged_on,
        rewatch=rewatch,
        note=note,
    )
    db.add(log)
    await db.flush()
    return log


async def get_log_by_id(db: AsyncSession, log_id: int) -> LibraryLog | None:
    result = await db.execute(select(LibraryLog).where(LibraryLog.id == log_id))
    return result.scalar_one_or_none()


async def delete_log(db: AsyncSession, log: LibraryLog) -> None:
    await db.delete(log)
    await db.flush()


async def list_logs_for_item(
    db: AsyncSession, item_type: str, item_id: int, page: int, limit: int
) -> tuple[list[LibraryLog], int]:
    """Paginated logs for an item, newest ``logged_on`` first."""
    count_result = await db.execute(
        select(func.count())
        .select_from(LibraryLog)
        .where(LibraryLog.item_type == item_type, LibraryLog.item_id == item_id)
    )
    total = count_result.scalar_one()

    paged_stmt = (
        select(LibraryLog)
        .where(LibraryLog.item_type == item_type, LibraryLog.item_id == item_id)
        .order_by(LibraryLog.logged_on.desc(), LibraryLog.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.scalars().all()), total


def _log_select(item_type: str, model: type):
    """Base SELECT for one item type: log + joined content item fields."""
    return select(
        LibraryLog.id.label("id"),
        literal(item_type, type_=String).label("item_type"),
        model.title.label("title"),
        model.slug.label("slug"),
        model.poster_url.label("poster_url"),
        LibraryLog.logged_on.label("logged_on"),
        LibraryLog.rewatch.label("rewatch"),
        LibraryLog.note.label("note"),
        LibraryLog.created_at.label("created_at"),
    ).join(model, LibraryLog.item_id == model.id)


async def list_user_log(
    db: AsyncSession, user_id: int, page: int, limit: int
) -> tuple[list[Any], int]:
    """Cross-type UNION ALL of a user's log history, newest ``logged_on`` first."""
    queries = [
        _log_select(item_type, model).where(
            LibraryLog.user_id == user_id, LibraryLog.item_type == item_type
        )
        for item_type, model in ITEM_MODELS.items()
    ]
    union_subq = union_all(*queries).subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(union_subq.c.logged_on.desc(), union_subq.c.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total
