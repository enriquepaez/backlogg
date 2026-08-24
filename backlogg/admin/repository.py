"""Admin repository — DB queries for admin stats.

Only this file imports and uses SQLAlchemy for the admin domain.
"""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin.models import AdminAction
from backlogg.books.models import Book
from backlogg.games.models import Game
from backlogg.movies.models import Movie
from backlogg.series.models import Series
from backlogg.users.models import User


async def get_stats(db: AsyncSession) -> dict:
    """Execute COUNT/MAX queries for all 4 content types.

    Returns a dict with keys ``movies``, ``series``, ``books``, ``games``.
    Each value is a dict with ``count`` (int) and ``last_synced_at``
    (datetime | None).
    """

    async def _query(model):  # type: ignore[no-untyped-def]
        result = await db.execute(select(func.count(), func.max(model.last_synced_at)))
        row = result.one()
        return {"count": row[0], "last_synced_at": row[1]}

    return {
        "movies": await _query(Movie),
        "series": await _query(Series),
        "books": await _query(Book),
        "games": await _query(Game),
    }


async def list_users(
    db: AsyncSession,
    is_banned: bool | None,
    is_admin: bool | None,
    search: str | None,
    page: int,
    limit: int,
) -> tuple[list[User], int]:
    """Paginated user listing for the admin backoffice, ordered by ``username`` asc.

    ``is_banned``/``is_admin``/``search`` are optional and combinable —
    omitting all three returns every user. ``search`` is a case-insensitive
    substring match (``ILIKE``) against ``username``, ``display_name`` OR
    ``email`` — email is only ever used to *locate* a row here, never
    returned (see ``AdminUserOut``, which has no ``email`` field). Returns a
    tuple of ``(items, total_count)``.
    """
    filters = []
    if is_banned is not None:
        filters.append(User.is_banned == is_banned)
    if is_admin is not None:
        filters.append(User.is_admin == is_admin)
    if search is not None:
        pattern = f"%{search}%"
        filters.append(
            or_(
                User.username.ilike(pattern),
                User.display_name.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    count_result = await db.execute(select(func.count()).select_from(User).where(*filters))
    total = count_result.scalar_one()

    paged_stmt = (
        select(User)
        .where(*filters)
        .order_by(User.username.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.scalars().all()), total


async def insert_admin_action(
    db: AsyncSession, *, actor_id: int | None, action: str, target_type: str, target_id: int
) -> AdminAction:
    """Persist one audit row (feature 63 — admin_action_audit_log).

    Flushes but does not commit — the caller commits together with the state
    change this action describes, so both land in the same transaction (see
    ``backlogg.admin.audit.record_admin_action``).
    """
    record = AdminAction(
        actor_id=actor_id, action=action, target_type=target_type, target_id=target_id
    )
    db.add(record)
    await db.flush()
    return record


async def list_admin_actions(
    db: AsyncSession, page: int, limit: int
) -> tuple[list[AdminAction], int]:
    """Paginated admin audit log, newest first (``created_at`` desc, ``id`` desc)."""
    count_result = await db.execute(select(func.count()).select_from(AdminAction))
    total = count_result.scalar_one()

    stmt = (
        select(AdminAction)
        .order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total
