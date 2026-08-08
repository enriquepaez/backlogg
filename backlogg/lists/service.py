"""Lists service — business logic for user-curated collections.

Slug resolution: the list slug is derived from the title with ``python-slugify``
and made *globally* unique by appending a numeric suffix on collision. The DB
still guarantees ``UNIQUE(user_id, slug)``, but resolving globally means
``/lists/{slug}`` always routes to exactly one list, which is what lets the
detail/patch/delete endpoints distinguish 404 (no such list) from 403 (exists
but not owned by the caller).
"""

from fastapi import HTTPException
from slugify import slugify
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.lists import repository as repo
from backlogg.lists.models import UserList
from backlogg.lists.schemas import (
    ListCreate,
    ListItemOut,
    ListItemRef,
    ListReorder,
    ListUpdate,
    UserListOut,
    UserListsOut,
    UserListSummary,
)
from backlogg.users import repository as users_repo
from backlogg.users.models import User

_ITEM_NOT_FOUND_DETAIL = {
    "MOVIE": "Movie not found",
    "SERIES": "Series not found",
    "BOOK": "Book not found",
    "GAME": "Game not found",
}


async def _derive_unique_slug(db: AsyncSession, title: str) -> str:
    """Slugify the title and disambiguate globally with a numeric suffix."""
    base = slugify(title) or "list"
    candidate = base
    suffix = 2
    while await repo.slug_exists(db, candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


async def _resolve_item(db: AsyncSession, ref: ListItemRef) -> tuple[str, int]:
    """Resolve an (item_type, slug) reference to (item_type, item_id). 404 if absent."""
    item_type = repo.TYPE_FILTER_TO_ITEM_TYPE[ref.item_type.value]
    item = await repo.get_item_by_slug(db, item_type, ref.slug)
    if item is None:
        raise HTTPException(status_code=404, detail=_ITEM_NOT_FOUND_DETAIL[item_type])
    return item_type, item.id


async def _get_owned_list(db: AsyncSession, slug: str, user: User) -> UserList:
    """Fetch a list by slug enforcing ownership: 404 if missing, 403 if not owner."""
    user_list = await repo.get_list_by_slug(db, slug)
    if user_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if user_list.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this list")
    return user_list


async def _build_detail(db: AsyncSession, user_list: UserList) -> UserListOut:
    rows = await repo.resolve_list_items(db, user_list.id)
    items = [
        ListItemOut(
            item_type=row.item_type,
            title=row.title,
            slug=row.slug,
            poster_url=row.poster_url,
            release_date=row.release_date,
            rating_external=(
                float(row.rating_external) if row.rating_external is not None else None
            ),
            position=row.position,
        )
        for row in rows
    ]
    return UserListOut(
        slug=user_list.slug,
        title=user_list.title,
        description=user_list.description,
        is_public=user_list.is_public,
        item_count=len(items),
        created_at=user_list.created_at,
        updated_at=user_list.updated_at,
        items=items,
    )


async def create_list(db: AsyncSession, payload: ListCreate, user: User) -> UserListOut:
    slug = await _derive_unique_slug(db, payload.title)
    user_list = await repo.create_list(
        db,
        user_id=user.id,
        slug=slug,
        title=payload.title,
        description=payload.description,
        is_public=payload.is_public,
    )
    await db.commit()
    return await _build_detail(db, user_list)


async def update_list(db: AsyncSession, slug: str, payload: ListUpdate, user: User) -> UserListOut:
    user_list = await _get_owned_list(db, slug, user)
    data = payload.model_dump(exclude_unset=True)
    if data:
        user_list = await repo.update_list(db, user_list, data)
    await db.commit()
    return await _build_detail(db, user_list)


async def delete_list(db: AsyncSession, slug: str, user: User) -> None:
    user_list = await _get_owned_list(db, slug, user)
    await repo.delete_list(db, user_list)
    await db.commit()


async def add_item(db: AsyncSession, slug: str, ref: ListItemRef, user: User) -> UserListOut:
    user_list = await _get_owned_list(db, slug, user)
    item_type, item_id = await _resolve_item(db, ref)
    await repo.add_list_item(db, user_list.id, item_type, item_id)
    await db.commit()
    return await _build_detail(db, user_list)


async def remove_item(db: AsyncSession, slug: str, ref: ListItemRef, user: User) -> UserListOut:
    user_list = await _get_owned_list(db, slug, user)
    item_type, item_id = await _resolve_item(db, ref)
    await repo.remove_list_item(db, user_list.id, item_type, item_id)
    await db.commit()
    return await _build_detail(db, user_list)


async def reorder_items(
    db: AsyncSession, slug: str, payload: ListReorder, user: User
) -> UserListOut:
    user_list = await _get_owned_list(db, slug, user)

    ordered: list[tuple[str, int]] = []
    for ref in payload.items:
        ordered.append(await _resolve_item(db, ref))

    current = await repo.get_list_items(db, user_list.id)
    current_keys = {(entry.item_type, entry.item_id) for entry in current}
    given_keys = set(ordered)
    if given_keys != current_keys or len(ordered) != len(current):
        raise HTTPException(
            status_code=422,
            detail="Order must contain exactly the items currently in the list",
        )

    await repo.reorder_list_items(db, user_list.id, ordered)
    await db.commit()
    return await _build_detail(db, user_list)


async def get_list(db: AsyncSession, slug: str, viewer: User | None) -> UserListOut:
    user_list = await repo.get_list_by_slug(db, slug)
    if user_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    if not user_list.is_public and (viewer is None or viewer.id != user_list.user_id):
        # Hide the existence of private lists from everyone but the owner.
        raise HTTPException(status_code=404, detail="List not found")
    return await _build_detail(db, user_list)


async def get_user_lists(db: AsyncSession, username: str, viewer: User | None) -> UserListsOut:
    target_user = await users_repo.get_user_by_username(db, username)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    include_private = viewer is not None and viewer.id == target_user.id
    rows = await repo.list_user_lists(db, target_user.id, include_private=include_private)
    summaries = [
        UserListSummary(
            slug=user_list.slug,
            title=user_list.title,
            description=user_list.description,
            is_public=user_list.is_public,
            item_count=item_count,
            created_at=user_list.created_at,
            updated_at=user_list.updated_at,
        )
        for user_list, item_count in rows
    ]
    return UserListsOut(lists=summaries, total=len(summaries))
