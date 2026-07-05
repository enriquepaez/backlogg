"""Admin domain — Pydantic v2 schemas."""

from datetime import datetime

from pydantic import BaseModel


class SyncResponse(BaseModel):
    type: str
    synced: int
    errors: int
    offset: int
    duration_s: float


class ContentStats(BaseModel):
    count: int
    last_synced_at: datetime | None


class StatsResponse(BaseModel):
    movies: ContentStats
    series: ContentStats
    books: ContentStats
    games: ContentStats
