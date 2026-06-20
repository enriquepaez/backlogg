from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class GenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class MovieOut(BaseModel):
    id: int
    title: str
    original_title: str | None
    slug: str
    overview: str | None
    release_date: date | None
    runtime: int | None
    original_language: str | None
    poster_url: str | None
    backdrop_url: str | None
    budget: int | None
    revenue: int | None
    status: str | None
    rating_external: float | None
    rating_count_external: int | None
    genres: list[GenreOut]

    model_config = ConfigDict(from_attributes=True)


class MovieSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class MovieListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class MovieListOut(BaseModel):
    items: list[MovieListItemOut]
    total: int
    page: int
    limit: int
