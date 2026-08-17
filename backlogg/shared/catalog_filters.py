"""Catalog search filters shared by the four ``GET /v1/{type}`` list endpoints.

Feature 50. ``movies``, ``series``, ``books`` and ``games`` each expose the same
optional, combinable query params on top of the existing ``genre``/``sort``/
``page``/``limit`` (feature 14): a case-insensitive substring ``search`` on
``title``, an inclusive ``date_from``/``date_to`` range on the type's date
column, and inclusive ``rating_internal_min/max`` / ``rating_external_min/max``
ranges. The contract lives here once instead of being duplicated four times,
while each domain's ``repository.py`` remains the only place that actually
touches SQLAlchemy for its own models (same pattern as
``backlogg/shared/external_ids.py``).

Cross-field validation (bad date range, ``min > max``) runs on the Pydantic
model itself via ``model_validator``, so FastAPI turns a violation into a
``422`` automatically — no extra code at the route/service layer.
"""

from datetime import date

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import InstrumentedAttribute

__all__ = ["CatalogSearchFilters", "build_catalog_filter_clauses"]


class CatalogSearchFilters(BaseModel):
    """Optional search/date/rating filters, independently optional and combinable."""

    search: str | None = Field(
        default=None, description="Case-insensitive substring match on title (ILIKE)"
    )
    date_from: date | None = Field(
        default=None, description="Inclusive lower bound on the type's date field"
    )
    date_to: date | None = Field(
        default=None, description="Inclusive upper bound on the type's date field"
    )
    rating_internal_min: float | None = Field(
        default=None, description="Inclusive lower bound on rating_internal"
    )
    rating_internal_max: float | None = Field(
        default=None, description="Inclusive upper bound on rating_internal"
    )
    rating_external_min: float | None = Field(
        default=None, description="Inclusive lower bound on rating_external"
    )
    rating_external_max: float | None = Field(
        default=None, description="Inclusive upper bound on rating_external"
    )

    @model_validator(mode="after")
    def _validate_ranges(self) -> "CatalogSearchFilters":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be after date_to")
        if (
            self.rating_internal_min is not None
            and self.rating_internal_max is not None
            and self.rating_internal_min > self.rating_internal_max
        ):
            raise ValueError("rating_internal_min must not be greater than rating_internal_max")
        if (
            self.rating_external_min is not None
            and self.rating_external_max is not None
            and self.rating_external_min > self.rating_external_max
        ):
            raise ValueError("rating_external_min must not be greater than rating_external_max")
        return self


def build_catalog_filter_clauses(
    filters: CatalogSearchFilters,
    *,
    title_col: InstrumentedAttribute,
    date_col: InstrumentedAttribute,
    rating_internal_col: InstrumentedAttribute,
    rating_external_col: InstrumentedAttribute,
) -> list:
    """Translate ``filters`` into a list of SQLAlchemy WHERE clauses.

    The caller (a domain's ``repository.py``) AND-combines the returned
    clauses with any other filter (e.g. ``genre``) it already applies. Columns
    are passed in explicitly so this stays model-agnostic across the four
    catalog types, each with its own date column name.
    """
    clauses: list = []
    if filters.search is not None:
        clauses.append(title_col.ilike(f"%{filters.search}%"))
    if filters.date_from is not None:
        clauses.append(date_col >= filters.date_from)
    if filters.date_to is not None:
        clauses.append(date_col <= filters.date_to)
    if filters.rating_internal_min is not None:
        clauses.append(rating_internal_col >= filters.rating_internal_min)
    if filters.rating_internal_max is not None:
        clauses.append(rating_internal_col <= filters.rating_internal_max)
    if filters.rating_external_min is not None:
        clauses.append(rating_external_col >= filters.rating_external_min)
    if filters.rating_external_max is not None:
        clauses.append(rating_external_col <= filters.rating_external_max)
    return clauses
