from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.lists import service
from backlogg.lists.schemas import (
    ListCreate,
    ListItemRef,
    ListReorder,
    ListUpdate,
    UserListOut,
    UserListsOut,
)
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

lists_router = APIRouter(prefix="/lists", tags=["lists"])

# GET /users/{username}/lists — registered under the same "/users" prefix as
# users_router; the extra "/lists" segment means the two never collide.
user_lists_router = APIRouter(prefix="/users", tags=["lists"])


@lists_router.post(
    "",
    response_model=UserListOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a list",
    description="Create a curated list; slug derived from the title. Requires auth.",
)
async def create_list(
    payload: ListCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.create_list(db, payload, current_user)


@lists_router.get(
    "/{slug}",
    response_model=UserListOut,
    summary="Get list detail",
    description="List detail with resolved items in order. Private lists 404 for non-owners.",
)
async def get_list(
    slug: str,
    viewer: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_list(db, slug, viewer)


@lists_router.patch(
    "/{slug}",
    response_model=UserListOut,
    summary="Update a list",
    description="Update title/description/is_public (slug never changes). Owner only.",
)
async def update_list(
    slug: str,
    payload: ListUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_list(db, slug, payload, current_user)


@lists_router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a list",
    description="Delete the list and cascade its items. Owner only.",
)
async def delete_list(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_list(db, slug, current_user)


@lists_router.post(
    "/{slug}/items",
    response_model=UserListOut,
    summary="Add item to list",
    description="Append an item at the end. Idempotent. Owner only. 404 if not in catalog.",
)
async def add_list_item(
    slug: str,
    payload: ListItemRef,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.add_item(db, slug, payload, current_user)


@lists_router.delete(
    "/{slug}/items",
    response_model=UserListOut,
    summary="Remove item from list",
    description="Remove an item and re-pack positions. Idempotent. Owner only.",
)
async def remove_list_item(
    slug: str,
    payload: ListItemRef,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.remove_item(db, slug, payload, current_user)


@lists_router.put(
    "/{slug}/items/order",
    response_model=UserListOut,
    summary="Reorder list items",
    description="Reorder items; payload must match the current items. Owner only. 422 on mismatch.",
)
async def reorder_list_items(
    slug: str,
    payload: ListReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.reorder_items(db, slug, payload, current_user)


@user_lists_router.get(
    "/{username}/lists",
    response_model=UserListsOut,
    summary="List a user's lists",
    description="A user's lists (public always; private only for the owner). Auth optional.",
)
async def get_user_lists(
    username: str,
    viewer: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_lists(db, username, viewer)
