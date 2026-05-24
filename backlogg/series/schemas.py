from datetime import date

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
