"""Library logs service — business logic for user activity log entries.

Each POST/GET /{type}/{slug}/log route in movies/series/books/games
routes.py delegates here, passing the resolved ``item_type`` ("MOVIE"/
"SERIES"/"BOOK"/"GAME") and the ``slug`` from the URL. This keeps the
create/list logic in one place instead of duplicating it across four domain
slices — same pattern as ``backlogg/ratings/service.py`` and
``backlogg/library/service.py``. Unlike those two modules, creating a log is
never an upsert: ``library_logs`` has no unique constraint per (user, item),
so repeated calls simply add another log row.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.library_logs import repository as repo
from backlogg.library_logs.models import LibraryLog
from backlogg.library_logs.schemas import (
    LogIn,
    LogListOut,
    LogOut,
    UserLogItemOut,
    UserLogListOut,
    UserLogOut,
)
from backlogg.users import repository as users_repo
from backlogg.users.models import User

_ITEM_NOT_FOUND_DETAIL = {
    "MOVIE": "Movie not found",
    "SERIES": "Series not found",
    "BOOK": "Book not found",
    "GAME": "Game not found",
}


def _log_to_out(log: LibraryLog, item_type: str, slug: str) -> LogOut:
    return LogOut(
        id=log.id,
        item_type=item_type,
        slug=slug,
        logged_on=log.logged_on,
        rewatch=log.rewatch,
        note=log.note,
        created_at=log.created_at,
    )


async def _get_item_or_404(db: AsyncSession, item_type: str, slug: str):
    item = await repo.get_item_by_slug(db, item_type, slug)
    if item is None:
        raise HTTPException(status_code=404, detail=_ITEM_NOT_FOUND_DETAIL[item_type])
    return item


async def create_log_entry(
    db: AsyncSession, item_type: str, slug: str, payload: LogIn, user: User
) -> LogOut:
    """Create a new log entry for the authenticated user.

    ``logged_on`` defaults to today when omitted from the payload (the
    payload itself already rejects a future date, see ``LogIn``).
    """
    item = await _get_item_or_404(db, item_type, slug)

    log = await repo.create_log(
        db,
        user_id=user.id,
        item_type=item_type,
        item_id=item.id,
        logged_on=payload.logged_on or date.today(),
        rewatch=payload.rewatch,
        note=payload.note,
    )
    await db.commit()

    return _log_to_out(log, item_type, slug)


async def list_item_log(
    db: AsyncSession, item_type: str, slug: str, page: int, limit: int
) -> LogListOut:
    """Public, paginated list of an item's log entries, newest ``logged_on`` first."""
    item = await _get_item_or_404(db, item_type, slug)

    rows, total = await repo.list_logs_for_item(db, item_type, item.id, page, limit)
    items = [_log_to_out(log, item_type, slug) for log in rows]
    return LogListOut(items=items, total=total, page=page, limit=limit)


async def delete_log_entry(db: AsyncSession, log_id: int, user: User) -> None:
    """Delete the authenticated user's own log entry. 404 if missing or not owned."""
    log = await repo.get_log_by_id(db, log_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(status_code=404, detail="Log entry not found")

    await repo.delete_log(db, log)
    await db.commit()


async def get_user_log(db: AsyncSession, username: str, page: int, limit: int) -> UserLogListOut:
    """Public, cross-type (UNION ALL) log history for a user, newest ``logged_on`` first."""
    target_user = await users_repo.get_user_by_username(db, username)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    rows, total = await repo.list_user_log(db, target_user.id, page, limit)
    items = [
        UserLogOut(
            id=row.id,
            item=UserLogItemOut(
                item_type=row.item_type,
                title=row.title,
                slug=row.slug,
                poster_url=row.poster_url,
            ),
            logged_on=row.logged_on,
            rewatch=row.rewatch,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return UserLogListOut(items=items, total=total, page=page, limit=limit)
