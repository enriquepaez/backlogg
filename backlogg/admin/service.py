"""Admin service — business logic layer for admin domain."""

import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import repository as admin_repo
from backlogg.admin.schemas import (
    AdminUserListOut,
    AdminUserOut,
    CatalogEditIn,
    CatalogEditOut,
    ContentStats,
    RoleGrantOut,
    StatsResponse,
)
from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo
from backlogg.users import repository as users_repo
from backlogg.users.models import User

# Feature 49 (catalog_manual_edit): fields the admin backoffice may edit per
# content type. "genres" is not a real column (a M2M relation) but is a
# valid lock target — see the domain repositories' upsert_*/admin_update_*.
_EDITABLE_FIELDS: dict[str, set[str]] = {
    "movie": {"title", "poster_url", "release_date", "genres"},
    "series": {"title", "poster_url", "first_air_date", "genres"},
    "book": {"title", "poster_url", "first_publish_date", "genres"},
    "game": {"title", "poster_url", "release_date", "genres"},
}

# The single date column exposed per type, used to build CatalogEditOut.
_DATE_FIELD: dict[str, str] = {
    "movie": "release_date",
    "series": "first_air_date",
    "book": "first_publish_date",
    "game": "release_date",
}

_GET_BY_SLUG = {
    "movie": movies_repo.get_movie_by_slug,
    "series": series_repo.get_series_by_slug,
    "book": books_repo.get_book_by_slug,
    "game": games_repo.get_game_by_slug,
}

_ADMIN_UPDATE = {
    "movie": movies_repo.admin_update_movie,
    "series": series_repo.admin_update_series,
    "book": books_repo.admin_update_book,
    "game": games_repo.admin_update_game,
}


def _slugify(text: str) -> str:
    """Same slugify rule as the sync adapters (backlogg/*/adapters/*.py)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _genres_payload(names: list[str]) -> list[dict]:
    """Convert admin-provided genre names into {"name", "slug"} dicts.

    Deduplicated by slug — two names that slugify to the same value (e.g.
    differing only in case) must not create two genre rows, same rule the
    sync adapters already apply.
    """
    seen: set[str] = set()
    result: list[dict] = []
    for name in names:
        slug = _slugify(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        result.append({"name": name, "slug": slug})
    return result


async def get_stats(db: AsyncSession) -> StatsResponse:
    """Return catalog stats for all 4 content types.

    Delegates the DB queries to the repository and maps the raw data
    to a StatsResponse Pydantic model.
    """
    raw = await admin_repo.get_stats(db)
    return StatsResponse(
        movies=ContentStats(**raw["movies"]),
        series=ContentStats(**raw["series"]),
        books=ContentStats(**raw["books"]),
        games=ContentStats(**raw["games"]),
    )


async def set_user_admin_role(
    db: AsyncSession, caller: User, username: str, is_admin: bool
) -> RoleGrantOut:
    """Grant or revoke ``is_admin`` on the user identified by ``username``.

    Only a superadmin caller (``caller.is_superadmin``) may perform this
    action — raises 403 otherwise, even though the request already carries a
    valid X-API-Key (that header alone is not enough for this, the highest
    -privilege action in the system; the caller's own identity is also
    checked server-side). Raises 404 if the target user does not exist.
    Idempotent: granting to an already-admin user, or revoking from a
    non-admin one, is a no-op that still returns the current state.

    Self-revocation is allowed on purpose: this only ever flips ``is_admin``,
    never ``is_superadmin`` (which has no API surface at all, DB-only) — so a
    superadmin can never lock themselves out of their superadmin status
    through this endpoint. The only side effect of a superadmin revoking
    their own (or another superadmin's) ``is_admin`` is losing access to the
    frontend `/admin` dashboard, which is recoverable the same way it was
    granted: by hand in the DB.
    """
    if not caller.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin privileges required")

    target = await users_repo.get_user_by_username(db, username)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    await users_repo.set_user_admin(db, target, is_admin)
    await db.commit()
    return RoleGrantOut(username=target.username, is_admin=is_admin)


async def get_user(db: AsyncSession, username: str) -> AdminUserOut:
    """Admin backoffice: a single user's admin-facing detail.

    Reuses the same lookup as ``set_user_admin_role`` (``users_repo.get_user_by_username``).
    Raises 404 if the username does not exist. Maps to ``AdminUserOut``, which
    never includes ``email`` — same PII-minimization criterion as ``list_users``.
    """
    user = await users_repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserOut.model_validate(user)


async def list_users(
    db: AsyncSession,
    is_banned: bool | None,
    is_admin: bool | None,
    search: str | None,
    page: int,
    limit: int,
) -> AdminUserListOut:
    """Admin backoffice: paginated users, ordered by ``username`` asc.

    ``is_banned``/``is_admin``/``search`` are optional and combinable. A
    ``search`` that is empty/whitespace-only after stripping is treated as
    absent (no filter) — same as omitting the query param. Delegates the
    query to the repository and maps the rows to ``AdminUserOut``, which
    never includes ``email`` (search can match against it, but it is never
    returned).
    """
    search = (search or "").strip() or None
    users, total = await admin_repo.list_users(
        db, is_banned=is_banned, is_admin=is_admin, search=search, page=page, limit=limit
    )
    items = [AdminUserOut.model_validate(u) for u in users]
    return AdminUserListOut(items=items, total=total, page=page, limit=limit)


async def edit_catalog_item(
    db: AsyncSession, type: str, slug: str, payload: CatalogEditIn
) -> CatalogEditOut:
    """Manually edit a subset of a catalog item's fields (admin backoffice, feature 49).

    Every field present in the payload (other than ``unlock_fields``) is
    persisted to the item AND added to its ``locked_fields``, so the next
    nightly sync leaves it untouched (see ``movies/series/books/games``
    ``repository.upsert_*``, which reads ``locked_fields`` before
    overwriting a column). ``unlock_fields`` releases field names back to
    sync control; applied *after* the edits above (see ``CatalogEditIn``'s
    docstring for the same-request overlap rule).

    Raises:
        HTTPException 422: a field in the payload (edited or in
            ``unlock_fields``) is not editable for ``type``, or ``title`` is
            set to an empty/whitespace-only string.
        HTTPException 404: no item of ``type`` has this ``slug``.
    """
    allowed = _EDITABLE_FIELDS[type]
    provided = payload.model_dump(exclude_unset=True)
    unlock_fields: set[str] = set(provided.pop("unlock_fields", None) or [])
    edit_fields = provided

    invalid = set(edit_fields) - allowed
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Field(s) not editable for type '{type}': {', '.join(sorted(invalid))}",
        )
    invalid_unlock = unlock_fields - allowed
    if invalid_unlock:
        raise HTTPException(
            status_code=422,
            detail=f"Field(s) not editable for type '{type}': {', '.join(sorted(invalid_unlock))}",
        )
    if "title" in edit_fields and (
        edit_fields["title"] is None or not edit_fields["title"].strip()
    ):
        raise HTTPException(status_code=422, detail="title cannot be empty")

    item = await _GET_BY_SLUG[type](db, slug)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    updates = dict(edit_fields)
    if "genres" in updates:
        updates["genres"] = _genres_payload(updates["genres"] or [])

    item = await _ADMIN_UPDATE[type](db, item, updates)

    new_locked = (set(item.locked_fields) | set(edit_fields.keys())) - unlock_fields
    item.locked_fields = sorted(new_locked)
    await db.commit()

    date_field = _DATE_FIELD[type]
    return CatalogEditOut(
        type=type,
        slug=item.slug,
        title=item.title,
        poster_url=item.poster_url,
        genres=[g.name for g in item.genres],
        locked_fields=item.locked_fields,
        **{date_field: getattr(item, date_field)},
    )
