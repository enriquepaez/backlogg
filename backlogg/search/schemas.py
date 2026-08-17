from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchParams(BaseModel):
    """Query params for ``GET /v1/search``.

    A dedicated model (not a :class:`~backlogg.shared.catalog_filters.CatalogSearchFilters`
    subclass) because that shared model carries ``search``/``rating_internal_*``
    fields that do not apply here: ``q`` already covers free-text search, and
    the ``catalog_search`` materialized view (``backlogg/search/models.py``)
    has no ``rating_internal`` column. Cross-field range validation is
    replicated (not imported) for just the two ranges that do apply here —
    same ``model_validator`` mechanism so FastAPI turns a violation into a
    ``422`` automatically.

    ``q`` is optional: when absent, ``/v1/search`` behaves as a pure filter
    endpoint over ``date_from``/``date_to``/``rating_external_min/max``
    (no full-text ranking, no external fallback — see ``service.py``). When
    present, it must be non-empty (``min_length=1``), same as before.
    """

    q: str | None = Field(default=None, min_length=1, description="Search query")
    type: Literal["movie", "series", "book", "game"] | None = Field(
        default=None, description="Filter by content type"
    )
    page: int = Field(default=1, ge=1, description="Page number")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page")
    date_from: date | None = Field(
        default=None, description="Inclusive lower bound on release_date"
    )
    date_to: date | None = Field(default=None, description="Inclusive upper bound on release_date")
    rating_external_min: float | None = Field(
        default=None, description="Inclusive lower bound on rating_external"
    )
    rating_external_max: float | None = Field(
        default=None, description="Inclusive upper bound on rating_external"
    )

    @model_validator(mode="after")
    def _validate_ranges(self) -> "SearchParams":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be after date_to")
        if (
            self.rating_external_min is not None
            and self.rating_external_max is not None
            and self.rating_external_min > self.rating_external_max
        ):
            raise ValueError("rating_external_min must not be greater than rating_external_max")
        return self


class SearchResultItem(BaseModel):
    id: int
    item_type: str
    slug: str
    title: str | None
    overview: str | None
    poster_url: str | None
    release_date: date | None
    rating_external: float | None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    page: int
    limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "id": 1,
                        "item_type": "MOVIE",
                        "slug": "dune-2021",
                        "title": "Dune",
                        "overview": "Paul Atreides unites with the Fremen of Arrakis.",
                        "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        "release_date": "2021-10-22",
                        "rating_external": 7.8,
                    }
                ],
                "total": 42,
                "page": 1,
                "limit": 20,
            }
        }
    )
