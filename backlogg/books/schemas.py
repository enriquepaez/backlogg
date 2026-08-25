from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.schemas import CreditOut


class BookGenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class SimilarBookOut(BaseModel):
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None

    model_config = ConfigDict(from_attributes=True)


class SimilarBooksOut(BaseModel):
    results: list[SimilarBookOut]


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
    rating_internal: float | None
    rating_count_internal: int
    genres: list[BookGenreOut]
    credits: list[CreditOut]
    viewer_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BookSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class BookListParams(CatalogSearchFilters):
    """Query params for ``GET /v1/books`` (feature 14 + feature 50).

    Subclasses :class:`CatalogSearchFilters` so FastAPI can flatten every
    field of a single Pydantic model into individual query params (this only
    works when the whole endpoint has exactly one query-sourced parameter —
    see ``routes.py``), while still reusing it directly as the ``filters``
    argument passed to the repository.
    """

    genre: str | None = Field(default=None, description="Filter by genre slug")
    sort: BookSortEnum = Field(default=BookSortEnum.rating_desc, description="Sort order")
    page: int = Field(default=1, ge=1, description="Page number")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")


class BookListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class BookListOut(BaseModel):
    items: list[BookListItemOut]
    total: int
    page: int
    limit: int
