from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.schemas import CreditOut


class SeriesGenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class SimilarSeriesOut(BaseModel):
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None

    model_config = ConfigDict(from_attributes=True)


class SimilarSeriesListOut(BaseModel):
    results: list[SimilarSeriesOut]


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
    rating_internal: float | None
    rating_count_internal: int
    genres: list[SeriesGenreOut]
    credits: list[CreditOut] = []
    viewer_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SeriesSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class SeriesListParams(CatalogSearchFilters):
    """Query params for ``GET /v1/series`` (feature 14 + feature 50).

    Subclasses :class:`CatalogSearchFilters` so FastAPI can flatten every
    field of a single Pydantic model into individual query params (this only
    works when the whole endpoint has exactly one query-sourced parameter —
    see ``routes.py``), while still reusing it directly as the ``filters``
    argument passed to the repository.
    """

    genre: str | None = Field(default=None, description="Filter by genre slug")
    sort: SeriesSortEnum = Field(default=SeriesSortEnum.rating_desc, description="Sort order")
    page: int = Field(default=1, ge=1, description="Page number")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")


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
