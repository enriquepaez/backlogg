from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ListItemType(StrEnum):
    """Content-type discriminator used in list-item request bodies."""

    movie = "movie"
    series = "series"
    book = "book"
    game = "game"


class ListCreate(BaseModel):
    """Request body for POST /lists."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = True


class ListUpdate(BaseModel):
    """Request body for PATCH /lists/{slug} — all fields optional (partial)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_public: bool | None = None


class ListItemRef(BaseModel):
    """References a content item by type + slug (add / remove / reorder)."""

    item_type: ListItemType
    slug: str


class ListReorder(BaseModel):
    """Request body for PUT /lists/{slug}/items/order.

    ``items`` must be exactly the set of items currently in the list, in the
    desired order.
    """

    items: list[ListItemRef]


class ListItemOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    position: int


class UserListOut(BaseModel):
    """Full list detail, including its resolved items in order."""

    slug: str
    title: str
    description: str | None
    is_public: bool
    item_count: int
    created_at: datetime
    updated_at: datetime
    items: list[ListItemOut]


class UserListSummary(BaseModel):
    """A list without its items, for the per-user listing."""

    slug: str
    title: str
    description: str | None
    is_public: bool
    item_count: int
    created_at: datetime
    updated_at: datetime


class UserListsOut(BaseModel):
    lists: list[UserListSummary]
    total: int
