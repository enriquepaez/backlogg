from datetime import date

from pydantic import BaseModel, ConfigDict


class GameGenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class GamePlatformOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class GameOut(BaseModel):
    id: int
    title: str
    original_title: str | None
    slug: str
    overview: str | None
    release_date: date | None
    game_type: str
    original_language: str | None
    poster_url: str | None
    backdrop_url: str | None
    rating_external: float | None
    rating_count_external: int | None
    genres: list[GameGenreOut]
    platforms: list[GamePlatformOut]

    model_config = ConfigDict(from_attributes=True)
