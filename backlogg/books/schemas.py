from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class BookGenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class BookOut(BaseModel):
    id: int
    title: str
    original_title: str | None
    slug: str
    overview: str | None
    first_publish_date: date | None
    original_language: str | None
    poster_url: str | None
    rating_external: float | None
    rating_count_external: int | None
    genres: list[BookGenreOut]

    model_config = ConfigDict(from_attributes=True)


class BookSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class BookListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class BookListOut(BaseModel):
    items: list[BookListItemOut]
    total: int
    page: int
    limit: int
