"""Admin domain — Pydantic v2 schemas."""

from datetime import datetime

from pydantic import BaseModel


class SyncResponse(BaseModel):
    status: str
    type: str


class ContentStats(BaseModel):
    count: int
    last_synced_at: datetime | None


class StatsResponse(BaseModel):
    movies: ContentStats
    series: ContentStats
    books: ContentStats
    games: ContentStats
