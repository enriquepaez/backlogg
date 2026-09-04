"""Admin domain — Pydantic v2 schemas."""

from datetime import date, datetime

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
    # Links this run wanted to write into ``external_ids`` and could not: the
    # (item_type, source, external_id) triple was already claimed by a
    # *different* item of the same type, so the item is in its table with no
    # link and no id-based lookup will ever find it (issue #22). Idempotent
    # re-links of the same item are not counted. Defaulted for the same reason
    # as ``people_errors``: a job that does not report it must not 500.
    skipped_links: int = 0


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


class CatalogEditIn(BaseModel):
    """Admin edit payload for ``PATCH /v1/admin/{type}/{slug}`` (feature 49).

    Only the fields relevant to the request's ``{type}`` may be set — see
    docs/api.md for the per-type editable field table. A field that exists on
    this schema but is not editable for the given ``type`` raises 422 at the
    service layer; a key that is not part of this schema at all is rejected
    by Pydantic itself (``extra="forbid"``) before it ever reaches the
    service.

    Every field explicitly set here (``exclude_unset`` — a field left at its
    default is treated as "not provided") is persisted AND added to the
    item's ``locked_fields``, so the next nightly sync leaves it untouched.

    ``unlock_fields`` is the chosen desync mechanism (see ADR in docs/api.md):
    a list of field names to release back to sync control, applied *after*
    the edits above within the same request — so a field present in both the
    edit payload and ``unlock_fields`` ends up unlocked, not locked.
    """

    title: str | None = None
    poster_url: str | None = None
    release_date: date | None = None
    first_air_date: date | None = None
    first_publish_date: date | None = None
    genres: list[str] | None = None
    unlock_fields: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class AdminActionOut(BaseModel):
    """A single row in the admin action audit log (feature 63).

    ``actor_id`` is the caller's user id for actions performed through a
    Bearer-authenticated route (grant-admin/revoke-admin only); ``null`` for
    every other audited action, which is gated solely by X-API-Key with no
    caller identity to record.
    """

    id: int
    actor_id: int | None
    action: str
    target_type: str
    target_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminActionListOut(BaseModel):
    items: list[AdminActionOut]
    total: int
    page: int
    limit: int


class CatalogEditOut(BaseModel):
    """Result of a catalog manual edit — the item's current editable state."""

    type: str
    slug: str
    title: str
    poster_url: str | None
    release_date: date | None = None
    first_air_date: date | None = None
    first_publish_date: date | None = None
    genres: list[str]
    locked_fields: list[str]
