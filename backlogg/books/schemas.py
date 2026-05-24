from datetime import date

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
