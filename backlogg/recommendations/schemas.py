"""Pydantic v2 schemas for the recommendations domain (read-only).

No SQLAlchemy models here — recommendations are computed on the fly from a
user's ratings/library seeds and never persisted as a new entity.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class RecommendationTypeFilter(StrEnum):
    """Optional ``?type=`` filter for GET /recommendations."""

    movie = "movie"
    series = "series"
    book = "book"
    game = "game"


# ``?type=`` filter value -> stored polymorphic item_type.
TYPE_FILTER_TO_ITEM_TYPE: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}


class RecommendationOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    reason: str


class RecommendationsOut(BaseModel):
    results: list[RecommendationOut]
    page: int
    limit: int
