from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "slug": "best-sci-fi",
                "title": "Best sci-fi",
                "description": "My favorite science fiction across media.",
                "is_public": True,
                "item_count": 2,
                "created_at": "2026-05-20T10:00:00Z",
                "updated_at": "2026-05-25T18:04:11Z",
                "items": [
                    {
                        "item_type": "MOVIE",
                        "title": "Dune",
                        "slug": "dune-2021",
                        "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        "release_date": "2021-10-22",
                        "rating_external": 7.8,
                        "position": 1,
                    }
                ],
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lists": [
                    {
                        "slug": "best-sci-fi",
                        "title": "Best sci-fi",
                        "description": "My favorite science fiction across media.",
                        "is_public": True,
                        "item_count": 12,
                        "created_at": "2026-05-20T10:00:00Z",
                        "updated_at": "2026-05-25T18:04:11Z",
                    }
                ],
                "total": 3,
            }
        }
    )
