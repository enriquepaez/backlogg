from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from backlogg.shared.schemas import CreditOut


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
    rating_internal: float | None
    rating_count_internal: int
    genres: list[GameGenreOut]
    platforms: list[GamePlatformOut]
    credits: list[CreditOut] = []
    viewer_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class GameSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class GameListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class GameListOut(BaseModel):
    items: list[GameListItemOut]
    total: int
    page: int
    limit: int


class SimilarGameOut(BaseModel):
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None

    model_config = ConfigDict(from_attributes=True)


class SimilarGameListOut(BaseModel):
    results: list[SimilarGameOut]
