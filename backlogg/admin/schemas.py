"""Admin domain — Pydantic v2 schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class AdminUserOut(BaseModel):
    """A single user row in the admin backoffice listing.

    Deliberately excludes ``email`` — same PII-minimization criterion as the
    public ``UserOut`` (email is only ever returned by register/login/me,
    never by an admin-facing or public listing).
    """

    username: str
    display_name: str | None
    avatar_url: str | None
    is_admin: bool
    is_superadmin: bool
    is_banned: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    limit: int
