from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


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
