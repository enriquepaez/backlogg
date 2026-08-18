"""Feed repository — event generation + cross-type reads over activity_events.

Only this file imports and uses SQLAlchemy for the feed domain. It owns
``activity_events`` (feature 54): the ratings/library services call the
generation helpers below (``create_rating_event``/``delete_rating_event``/
``create_status_completed_event``) as a normal repository-to-repository call,
same precedent as ``backlogg/ratings/repository.py`` writing directly to the
movies/series/books/games tables. The read side builds the feed with the same
UNION ALL style as ``backlogg/genres/repository.py`` and
``backlogg/ratings/repository.py::list_user_reviews`` — one SELECT per item
type joined to its content table, combined with ``union_all``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, case, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.feed.models import ActivityEvent
from backlogg.follows.models import Follow
from backlogg.ratings.models import ReviewLike, UserRating
from backlogg.ratings.repository import ITEM_MODELS
from backlogg.users.models import User

POPULAR_WINDOW_DAYS = 30


# ── Event generation ─────────────────────────────────────────────────────────


async def create_rating_event(
    db: AsyncSession, *, user_id: int, item_type: str, item_id: int, rating_id: int
) -> None:
    """Insert a ``rating_created`` event for this rating.

    ``ON CONFLICT DO NOTHING`` keyed on the unique ``rating_id`` is what
    prevents successive updates to the same rating from duplicating events —
    the first call to have score/review_text content wins, later ones are a
    no-op.
    """
    stmt = (
        pg_insert(ActivityEvent)
        .values(
            user_id=user_id,
            event_type="rating_created",
            item_type=item_type,
            item_id=item_id,
            rating_id=rating_id,
        )
        .on_conflict_do_nothing(constraint="uq_activity_events_rating_id")
    )
    await db.execute(stmt)
    await db.flush()


async def delete_rating_event(db: AsyncSession, rating_id: int) -> None:
    """Remove the ``rating_created`` event for a rating, if one exists.

    Used when an update clears both ``score`` and ``review_text`` back to
    null: the ``user_ratings`` row survives (it's an upsert, not a delete) but
    no longer has content worth surfacing in the feed. A full rating *delete*
    does not need this — ``ON DELETE CASCADE`` removes the event automatically.
    """
    result = await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating_id))
    event = result.scalar_one_or_none()
    if event is not None:
        await db.delete(event)
        await db.flush()


async def create_status_completed_event(
    db: AsyncSession, *, user_id: int, item_type: str, item_id: int
) -> None:
    """Insert a ``status_completed`` event.

    The caller decides *when* to call this — only on a transition into
    ``completed`` (``backlogg/library/service.py``), so repeating an
    already-``completed`` PUT does not insert another row. Unlike
    ``rating_created`` there is no dedup key here: each transition into
    ``completed`` (e.g. after a later ``dropped`` then ``completed`` again) is
    its own narrative fact.
    """
    db.add(
        ActivityEvent(
            user_id=user_id,
            event_type="status_completed",
            item_type=item_type,
            item_id=item_id,
            rating_id=None,
        )
    )
    await db.flush()


# ── Read side (GET /feed) ────────────────────────────────────────────────────


def _like_count_subquery():
    """Aggregated like counts per rating — LEFT JOINed so ratings with zero
    likes still appear (COALESCE to 0) and popular can order by it robustly."""
    return (
        select(
            ReviewLike.rating_id.label("rating_id"),
            func.count().label("like_count"),
        )
        .group_by(ReviewLike.rating_id)
        .subquery()
    )


def _feed_select(item_type: str, model: type, like_subq, *, only_rating_created: bool = False):
    """Base SELECT for one item type: event + item + author + (for
    rating_created) score/review_text/like_count.

    ``rating_created`` rows are LEFT JOINed to ``user_ratings`` (their
    ``rating_id``) to resolve ``score``/``review_text``, and to the like-count
    subquery the same way. ``status_completed`` rows have no ``rating_id``, so
    both joins yield NULL for them — ``like_count`` is explicitly NULL (not 0)
    for those rows via the ``case()``, matching the "no like_count" minimal
    shape from the acceptance criteria. Author fields are resolved in-SQL
    (JOIN to users) to avoid N+1.

    Visibility: a banned author's events never appear; a hidden review's
    ``rating_created`` event never appears (the same "visible review" rule as
    ``backlogg/ratings/repository.py::visible_review_filters``, applied here
    directly since the JOIN is to ``ActivityEvent`` rather than ``UserRating``).
    ``status_completed`` rows have no ``is_hidden`` concept, so that half of
    the condition is skipped for them.
    """
    query = (
        select(
            ActivityEvent.id.label("id"),
            literal(item_type, type_=String).label("item_type"),
            ActivityEvent.event_type.label("event_type"),
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            UserRating.score.label("score"),
            UserRating.review_text.label("review_text"),
            ActivityEvent.created_at.label("created_at"),
            User.username.label("username"),
            User.display_name.label("display_name"),
            User.avatar_url.label("avatar_url"),
            case(
                (
                    ActivityEvent.event_type == "rating_created",
                    func.coalesce(like_subq.c.like_count, 0),
                ),
                else_=None,
            ).label("like_count"),
        )
        .join(model, ActivityEvent.item_id == model.id)
        .join(User, ActivityEvent.user_id == User.id)
        .outerjoin(UserRating, ActivityEvent.rating_id == UserRating.id)
        .outerjoin(like_subq, like_subq.c.rating_id == ActivityEvent.rating_id)
        .where(
            ActivityEvent.item_type == item_type,
            User.is_banned.is_(False),
            or_(ActivityEvent.event_type != "rating_created", UserRating.is_hidden.is_(False)),
        )
    )
    if only_rating_created:
        query = query.where(ActivityEvent.event_type == "rating_created")
    return query


async def list_following_feed(
    db: AsyncSession, caller_id: int, page: int, limit: int
) -> tuple[list[Any], int]:
    """Events from users the caller follows, newest first, paginated.

    Both event types participate. Caller with no follows → empty list (the
    ``IN (...)`` subquery is simply empty, so this is not an error).
    """
    like_subq = _like_count_subquery()
    followed_subq = select(Follow.followed_id).where(Follow.follower_id == caller_id)

    queries = [
        _feed_select(item_type, model, like_subq).where(ActivityEvent.user_id.in_(followed_subq))
        for item_type, model in ITEM_MODELS.items()
    ]
    union_subq = union_all(*queries).subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(union_subq.c.created_at.desc(), union_subq.c.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total


async def list_popular_feed(db: AsyncSession, page: int, limit: int) -> tuple[list[Any], int]:
    """``rating_created`` events from the last 30 days ordered by like_count
    desc, then newest first.

    ``status_completed`` events have no likes and are deliberately excluded
    from this tab rather than surfaced with an always-zero like_count — a
    ranking that everything-with-zero-likes could dominate arbitrarily would
    not be a meaningful "popular" ordering.
    """
    cutoff = datetime.now(UTC) - timedelta(days=POPULAR_WINDOW_DAYS)
    like_subq = _like_count_subquery()

    queries = [
        _feed_select(item_type, model, like_subq, only_rating_created=True).where(
            ActivityEvent.created_at >= cutoff
        )
        for item_type, model in ITEM_MODELS.items()
    ]
    union_subq = union_all(*queries).subquery()

    count_result = await db.execute(select(func.count()).select_from(union_subq))
    total = count_result.scalar_one()

    paged_stmt = (
        select(union_subq)
        .order_by(
            union_subq.c.like_count.desc(),
            union_subq.c.created_at.desc(),
            union_subq.c.id.desc(),
        )
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.all()), total
