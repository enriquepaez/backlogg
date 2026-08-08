"""Lists repository — DB queries for user_lists / list_items.

Only this file imports and uses SQLAlchemy for the lists domain. It reuses the
``ITEM_MODELS`` mapping and ``get_item_by_slug`` helper from
``backlogg/ratings/repository.py`` (polymorphic item_type/item_id lookups) and
resolves a list's items cross-type with the same UNION ALL style as
``backlogg/library/repository.py`` — one SELECT per item type joined to its
content table, combined with ``union_all`` and ordered by ``position``.
"""

from typing import Any

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.lists.models import ListItem, UserList
from backlogg.ratings.repository import ITEM_MODELS, get_item_by_slug

__all__ = [
    "get_item_by_slug",
    "TYPE_FILTER_TO_ITEM_TYPE",
    "get_list_by_slug",
    "slug_exists",
    "create_list",
    "update_list",
    "delete_list",
    "get_list_item",
    "get_list_items",
    "add_list_item",
    "remove_list_item",
    "reorder_list_items",
    "resolve_list_items",
    "count_list_items",
    "list_user_lists",
]

# Content-type value (as sent in request bodies) -> stored item_type.
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


# ── user_lists ──────────────────────────────────────────────────────────────


async def get_list_by_slug(db: AsyncSession, slug: str) -> UserList | None:
    """Global lookup by slug — slugs are resolved to be globally unique."""
    result = await db.execute(select(UserList).where(UserList.slug == slug))
    return result.scalar_one_or_none()


async def slug_exists(db: AsyncSession, slug: str) -> bool:
    result = await db.execute(select(UserList.id).where(UserList.slug == slug))
    return result.scalar_one_or_none() is not None


async def create_list(
    db: AsyncSession,
    user_id: int,
    slug: str,
    title: str,
    description: str | None,
    is_public: bool,
) -> UserList:
    user_list = UserList(
        user_id=user_id,
        slug=slug,
        title=title,
        description=description,
        is_public=is_public,
    )
    db.add(user_list)
    await db.flush()
    await db.refresh(user_list)
    return user_list


async def update_list(db: AsyncSession, user_list: UserList, data: dict[str, Any]) -> UserList:
    """Apply a partial update. ``slug`` is intentionally never changed."""
    for key, value in data.items():
        setattr(user_list, key, value)
    await db.flush()
    await db.refresh(user_list)
    return user_list


async def delete_list(db: AsyncSession, user_list: UserList) -> None:
    await db.delete(user_list)
    await db.flush()


async def list_user_lists(
    db: AsyncSession, owner_id: int, include_private: bool
) -> list[tuple[UserList, int]]:
    """Return (UserList, item_count) for a user, newest first.

    Private lists are included only when ``include_private`` is True.
    """
    item_count_subq = (
        select(func.count())
        .select_from(ListItem)
        .where(ListItem.list_id == UserList.id)
        .correlate(UserList)
        .scalar_subquery()
    )

    stmt = select(UserList, item_count_subq.label("item_count")).where(UserList.user_id == owner_id)
    if not include_private:
        stmt = stmt.where(UserList.is_public.is_(True))
    stmt = stmt.order_by(UserList.created_at.desc(), UserList.id.desc())

    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


# ── list_items ──────────────────────────────────────────────────────────────


async def get_list_item(
    db: AsyncSession, list_id: int, item_type: str, item_id: int
) -> ListItem | None:
    result = await db.execute(
        select(ListItem).where(
            ListItem.list_id == list_id,
            ListItem.item_type == item_type,
            ListItem.item_id == item_id,
        )
    )
    return result.scalar_one_or_none()


async def get_list_items(db: AsyncSession, list_id: int) -> list[ListItem]:
    result = await db.execute(
        select(ListItem).where(ListItem.list_id == list_id).order_by(ListItem.position)
    )
    return list(result.scalars().all())


async def count_list_items(db: AsyncSession, list_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(ListItem).where(ListItem.list_id == list_id)
    )
    return result.scalar_one()


async def add_list_item(db: AsyncSession, list_id: int, item_type: str, item_id: int) -> ListItem:
    """Append an item to the end of the list. Idempotent on (list, item).

    If the item is already present the existing row is returned unchanged
    (position preserved). Otherwise it is inserted at ``max(position) + 1``.
    """
    existing = await get_list_item(db, list_id, item_type, item_id)
    if existing is not None:
        return existing

    max_pos = await db.execute(
        select(func.max(ListItem.position)).where(ListItem.list_id == list_id)
    )
    current_max = max_pos.scalar_one()
    next_position = 0 if current_max is None else current_max + 1

    stmt = (
        pg_insert(ListItem)
        .values(
            list_id=list_id,
            item_type=item_type,
            item_id=item_id,
            position=next_position,
        )
        .on_conflict_do_nothing(constraint="uq_list_item")
    )
    await db.execute(stmt)
    await db.flush()

    item = await get_list_item(db, list_id, item_type, item_id)
    assert item is not None
    return item


async def remove_list_item(db: AsyncSession, list_id: int, item_type: str, item_id: int) -> bool:
    """Remove an item from the list. Idempotent — no-op if absent.

    Returns True if a row was removed. Remaining items are re-packed so their
    positions stay contiguous (0-based).
    """
    item = await get_list_item(db, list_id, item_type, item_id)
    if item is None:
        return False

    await db.delete(item)
    await db.flush()

    # Re-pack remaining positions to keep them contiguous.
    remaining = await get_list_items(db, list_id)
    for index, entry in enumerate(remaining):
        if entry.position != index:
            entry.position = index
    await db.flush()
    return True


async def reorder_list_items(
    db: AsyncSession, list_id: int, ordered_item_ids: list[tuple[str, int]]
) -> None:
    """Assign positions to items following the given (item_type, item_id) order."""
    items = await get_list_items(db, list_id)
    by_key = {(entry.item_type, entry.item_id): entry for entry in items}
    for index, key in enumerate(ordered_item_ids):
        entry = by_key[key]
        entry.position = index
    await db.flush()


def _list_items_select(item_type: str, model: type, list_id: int):
    release_col = getattr(model, _RELEASE_DATE_ATTR[item_type])
    return (
        select(
            literal(item_type, type_=String).label("item_type"),
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            release_col.label("release_date"),
            model.rating_external.label("rating_external"),
            ListItem.position.label("position"),
        )
        .join(model, ListItem.item_id == model.id)
        .where(ListItem.list_id == list_id, ListItem.item_type == item_type)
    )


async def resolve_list_items(db: AsyncSession, list_id: int) -> list[Any]:
    """Cross-type UNION ALL of a list's items, ordered by ``position``."""
    queries = [
        _list_items_select(item_type, model, list_id) for item_type, model in ITEM_MODELS.items()
    ]
    union_subq = union_all(*queries).subquery()
    stmt = select(union_subq).order_by(union_subq.c.position)
    result = await db.execute(stmt)
    return list(result.all())
