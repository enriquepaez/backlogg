from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ItemTypeEnum(StrEnum):
    movie = "movie"
    series = "series"


class PeriodEnum(StrEnum):
    day = "day"
    week = "week"


class TrendingItemOut(BaseModel):
    item_type: Literal["MOVIE", "SERIES"]
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None


class TrendingOut(BaseModel):
    results: list[TrendingItemOut]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "item_type": "MOVIE",
                        "title": "Dune",
                        "slug": "dune-2021",
                        "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        "release_date": "2021-10-22",
                        "rating_external": 7.8,
                    }
                ]
            }
        }
    )
