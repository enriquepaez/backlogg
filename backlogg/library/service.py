"""Library service — business logic for per-user backlog entries.

Each PUT/DELETE /{type}/{slug}/library route in movies/series/books/games
routes.py delegates here, passing the resolved ``item_type`` ("MOVIE"/
"SERIES"/"BOOK"/"GAME") and the ``slug`` from the URL. This keeps the upsert /
delete logic in one place instead of duplicating it across four domain slices.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.feed import repository as feed_repo
from backlogg.follows import repository as follows_repo
from backlogg.library import repository as repo
from backlogg.library.schemas import (
    LibraryCounts,
    LibraryEntryOut,
    LibraryItemOut,
    LibraryListOut,
    LibraryStatus,
    LibraryStatusOut,
    LibraryTypeFilter,
)
from backlogg.notifications import service as notifications_service
from backlogg.users import repository as users_repo
from backlogg.users.models import User

_ITEM_NOT_FOUND_DETAIL = {
    "MOVIE": "Movie not found",
    "SERIES": "Series not found",
    "BOOK": "Book not found",
    "GAME": "Game not found",
}


async def _get_item_or_404(db: AsyncSession, item_type: str, slug: str):
    item = await repo.get_item_by_slug(db, item_type, slug)
    if item is None:
        raise HTTPException(status_code=404, detail=_ITEM_NOT_FOUND_DETAIL[item_type])
    return item


async def set_library_status(
    db: AsyncSession, item_type: str, slug: str, status: LibraryStatus, user: User
) -> LibraryStatusOut:
    """Upsert the authenticated user's backlog status for an item."""
    item = await _get_item_or_404(db, item_type, slug)
    previous_status = await repo.get_library_status(db, user.id, item_type, item.id)

    entry = await repo.upsert_library_entry(
        db,
        user_id=user.id,
        item_type=item_type,
        item_id=item.id,
        status=status.value,
    )

    # Feed event generation (feature 54): only a transition *into* completed
    # is feed-worthy — re-PUTting an already-completed status (or any other
    # transition: want/in_progress/dropped) does not insert another event.
    # Same-transaction as the status write for the same reason as
    # ratings.service.rate_item (plain local insert, no external call).
    is_new_completion = status.value == "completed" and previous_status != "completed"
    if is_new_completion:
        await feed_repo.create_status_completed_event(
            db, user_id=user.id, item_type=item_type, item_id=item.id
        )

    await db.commit()

    # Build the response before the notification side effect below: each
    # notify_user_completed call may commit/rollback the session on its own
    # (graceful degradation), and a rollback expires every ORM instance in the
    # session — reading entry.* afterwards would trigger an implicit lazy
    # reload outside of an awaited context (MissingGreenlet). Snapshotting the
    # response first sidesteps that entirely.
    out = LibraryStatusOut(
        item_type=item_type,
        slug=slug,
        status=entry.status,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )

    # Notification fan-out (feature 55): one user_completed notification per
    # direct follower — no fan-out to followers of followers, no dedup across
    # repeated completions (each transition into completed is its own
    # notification, same as review_like never deduplicating). Runs after the
    # status write is committed and cannot break it (graceful degradation,
    # same pattern as notify_new_follower/notify_review_like).
    if is_new_completion:
        follower_ids = await follows_repo.list_follower_ids(db, user.id)
        for follower_id in follower_ids:
            await notifications_service.notify_user_completed(
                db,
                recipient_id=follower_id,
                actor_id=user.id,
                item_type=item_type,
                item_id=item.id,
            )

    return out


async def remove_library_entry(db: AsyncSession, item_type: str, slug: str, user: User) -> None:
    """Delete the authenticated user's own library entry. 404 if it doesn't exist."""
    item = await _get_item_or_404(db, item_type, slug)

    entry = await repo.get_library_entry(db, user_id=user.id, item_type=item_type, item_id=item.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Library entry not found")

    await repo.delete_library_entry(db, entry)
    await db.commit()


async def get_viewer_status(
    db: AsyncSession, item_type: str, item_id: int, viewer_id: int | None
) -> str | None:
    """Return the caller's library status for an item, or None if anonymous/absent."""
    if viewer_id is None:
        return None
    return await repo.get_library_status(db, viewer_id, item_type, item_id)


async def get_user_library(
    db: AsyncSession,
    username: str,
    status: LibraryStatus | None,
    type_filter: LibraryTypeFilter | None,
    page: int,
    limit: int,
) -> LibraryListOut:
    """Public, paginated, cross-type (UNION ALL) list of a user's library."""
    target_user = await users_repo.get_user_by_username(db, username)
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    status_value = status.value if status is not None else None
    item_type_filter = (
        repo.TYPE_FILTER_TO_ITEM_TYPE[type_filter.value] if type_filter is not None else None
    )

    rows, total = await repo.list_user_library(
        db,
        user_id=target_user.id,
        status=status_value,
        item_type_filter=item_type_filter,
        page=page,
        limit=limit,
    )
    items = [
        LibraryEntryOut(
            item=LibraryItemOut(
                item_type=row.item_type,
                title=row.title,
                slug=row.slug,
                poster_url=row.poster_url,
                release_date=row.release_date,
                rating_external=(
                    float(row.rating_external) if row.rating_external is not None else None
                ),
            ),
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return LibraryListOut(items=items, total=total, page=page, limit=limit)


async def get_library_counts(db: AsyncSession, user_id: int) -> LibraryCounts:
    """Per-status counts for a user's library (used on the public profile)."""
    counts = await repo.count_by_status(db, user_id)
    return LibraryCounts(**counts)
