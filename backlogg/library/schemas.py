from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class LibraryStatus(StrEnum):
    """Backlog status values accepted in request bodies and filters."""

    want = "want"
    in_progress = "in_progress"
    completed = "completed"
    dropped = "dropped"


class LibraryTypeFilter(StrEnum):
    """Content-type filter for GET /users/{username}/library (?type=)."""

    movie = "movie"
    series = "series"
    book = "book"
    game = "game"


class LibraryEntryIn(BaseModel):
    """Request body for PUT /{type}/{slug}/library."""

    status: LibraryStatus


class LibraryStatusOut(BaseModel):
    """Response of PUT /{type}/{slug}/library — the caller's own entry."""

    item_type: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "item_type": "MOVIE",
                "slug": "dune-2021",
                "status": "want",
                "created_at": "2026-05-25T18:04:11Z",
                "updated_at": "2026-05-25T18:04:11Z",
            }
        }
    )


class LibraryItemOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None


class LibraryEntryOut(BaseModel):
    item: LibraryItemOut
    status: str
    created_at: datetime
    updated_at: datetime


class LibraryListOut(BaseModel):
    items: list[LibraryEntryOut]
    total: int
    page: int
    limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "item": {
                            "item_type": "MOVIE",
                            "title": "Dune",
                            "slug": "dune-2021",
                            "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                            "release_date": "2021-10-22",
                            "rating_external": 7.8,
                        },
                        "status": "completed",
                        "created_at": "2026-05-25T18:04:11Z",
                        "updated_at": "2026-05-26T09:12:00Z",
                    }
                ],
                "total": 12,
                "page": 1,
                "limit": 20,
            }
        }
    )


class LibraryCounts(BaseModel):
    """Per-status counts of a user's library, surfaced on the public profile."""

    want: int = 0
    in_progress: int = 0
    completed: int = 0
    dropped: int = 0
