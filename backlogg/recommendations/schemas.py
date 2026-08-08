"""Pydantic v2 schemas for the recommendations domain (read-only).

No SQLAlchemy models here — recommendations are computed on the fly from a
user's ratings/library seeds and never persisted as a new entity.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "item_type": "MOVIE",
                        "title": "Blade Runner 2049",
                        "slug": "blade-runner-2049",
                        "poster_url": "https://image.tmdb.org/t/p/w500/br2049.jpg",
                        "release_date": "2017-10-06",
                        "rating_external": 8.0,
                        "reason": "Because you rated Dune",
                    }
                ],
                "page": 1,
                "limit": 20,
            }
        }
    )
