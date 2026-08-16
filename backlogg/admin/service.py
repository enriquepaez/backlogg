"""Admin service — business logic layer for admin domain."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import repository as admin_repo
from backlogg.admin.schemas import (
    AdminUserListOut,
    AdminUserOut,
    ContentStats,
    RoleGrantOut,
    StatsResponse,
)
from backlogg.users import repository as users_repo
from backlogg.users.models import User


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


async def list_users(
    db: AsyncSession,
    is_banned: bool | None,
    is_admin: bool | None,
    page: int,
    limit: int,
) -> AdminUserListOut:
    """Admin backoffice: paginated users, ordered by ``username`` asc.

    ``is_banned``/``is_admin`` are optional and combinable. Delegates the
    query to the repository and maps the rows to ``AdminUserOut``, which
    never includes ``email``.
    """
    users, total = await admin_repo.list_users(
        db, is_banned=is_banned, is_admin=is_admin, page=page, limit=limit
    )
    items = [AdminUserOut.model_validate(u) for u in users]
    return AdminUserListOut(items=items, total=total, page=page, limit=limit)
