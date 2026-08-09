from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReportStatus(StrEnum):
    """Lifecycle of a review report; also the ``?status=`` filter values."""

    open = "open"
    resolved = "resolved"


class ReportReasonIn(BaseModel):
    """Request body for POST /reviews/{id}/report.

    ``reason`` is an optional short note explaining why the review was flagged.
    The whole body is optional, so a bare report with no reason is accepted.
    """

    reason: str | None = Field(default=None, max_length=300)


class ReportOut(BaseModel):
    """A single review report, as returned to the reporter and the admin queue."""

    id: int
    reporter_id: int
    rating_id: int
    reason: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ReportListOut(BaseModel):
    items: list[ReportOut]
    total: int
    page: int
    limit: int
