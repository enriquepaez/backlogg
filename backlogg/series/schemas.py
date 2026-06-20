from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SeriesGenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class SeriesOut(BaseModel):
    id: int
    title: str
    original_title: str | None
    slug: str
    overview: str | None
    first_air_date: date | None
    last_air_date: date | None
    number_of_seasons: int | None
    number_of_episodes: int | None
    status: str | None
    original_language: str | None
    poster_url: str | None
    backdrop_url: str | None
    rating_external: float | None
    rating_count_external: int | None
    genres: list[SeriesGenreOut]

    model_config = ConfigDict(from_attributes=True)


class SeriesSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class SeriesListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class SeriesListOut(BaseModel):
    items: list[SeriesListItemOut]
    total: int
    page: int
    limit: int
