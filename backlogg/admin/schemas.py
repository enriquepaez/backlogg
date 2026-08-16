"""Admin domain — Pydantic v2 schemas."""

from datetime import datetime

from pydantic import BaseModel


class SyncResponse(BaseModel):
    type: str
    synced: int
    errors: int
    offset: int
    duration_s: float
    # Default 0 because sync_games does not return this key — games have no
    # separate people/credits persistence step to fail independently.
    people_errors: int = 0


class ContentStats(BaseModel):
    count: int
    last_synced_at: datetime | None


class StatsResponse(BaseModel):
    movies: ContentStats
    series: ContentStats
    books: ContentStats
    games: ContentStats


class RoleGrantOut(BaseModel):
    """Result of a grant-admin/revoke-admin action on a user."""

    username: str
    is_admin: bool
