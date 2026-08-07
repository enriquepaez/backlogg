"""Feed service — business logic for the activity feed.

Delegates the cross-type UNION ALL query to ``backlogg/feed/repository.py`` and
maps the resulting rows into Pydantic response schemas. The ``tab`` value is
already constrained to ``following``/``popular`` by the router's ``Literal``
type, so no extra validation is needed here.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.feed import repository as repo
from backlogg.feed.schemas import FeedAuthorOut, FeedEntryOut, FeedItemOut, FeedListOut
from backlogg.users.models import User


def _row_to_entry(row) -> FeedEntryOut:
    return FeedEntryOut(
        id=row.id,
        author=FeedAuthorOut(
            username=row.username,
            display_name=row.display_name,
            avatar_url=row.avatar_url,
        ),
        item=FeedItemOut(
            item_type=row.item_type,
            title=row.title,
            slug=row.slug,
            poster_url=row.poster_url,
        ),
        score=row.score,
        review_text=row.review_text,
        like_count=row.like_count,
        created_at=row.created_at,
    )


async def get_feed(db: AsyncSession, caller: User, tab: str, page: int, limit: int) -> FeedListOut:
    """Return the paginated feed for the given tab (following/popular)."""
    if tab == "following":
        rows, total = await repo.list_following_feed(db, caller.id, page, limit)
    else:  # "popular" — the only other value the router's Literal allows
        rows, total = await repo.list_popular_feed(db, page, limit)

    items = [_row_to_entry(row) for row in rows]
    return FeedListOut(items=items, total=total, page=page, limit=limit)
