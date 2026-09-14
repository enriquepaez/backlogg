"""Trending repository — the local activity signal behind ``GET /v1/trending``.

Only this file uses SQLAlchemy for the trending domain (the fallback path
delegates to the four catalog repositories instead of duplicating their
``ORDER BY``). It reads the three activity tables — ``activity_events``,
``library_entries`` and ``user_ratings`` — and collapses them into one decayed
score per catalog item.

Why the three tables need trimming before they are summed
---------------------------------------------------------
``activity_events`` is a **mirror** of the other two, not an independent
signal: a ``rating_created`` row mirrors a ``user_ratings`` row (one per
rating, enforced by ``uq_activity_events_rating_id``) and a
``status_completed`` row mirrors a ``library_entries`` transition into
``completed``. Summing the three tables as they are would count one single
user gesture up to three times.

Three facts make a clean, **disjoint** partition possible (see
``backlogg/feed/models.py``, ``backlogg/library/service.py`` and
``backlogg/ratings/service.py``):

- ``want`` / ``in_progress`` / ``dropped`` **never** produce an event. Careful
  with what that does *not* say: it is a fact about the **transition**, not
  about the row's final state. ``completed → dropped`` writes an event on the
  way in and leaves the row on ``dropped`` afterwards.
- Re-rating an item does **not** produce a second event, but it is genuine
  fresh engagement.
- An event is written the first time the rating **has content**, which is not
  necessarily when the row was inserted. ``RatingIn`` allows both fields to be
  ``None``, so ``PUT {}`` creates a row with no event and a later
  ``PUT {"score": 4}`` creates the event — one action that also leaves
  ``updated_at > created_at``.

So each gesture is counted exactly once, by exactly one of these three
contributions:

============================ ====================== ==================================
Contribution                 Source                 Disjointness argument
============================ ====================== ==================================
``rating_created``,          ``activity_events``    The canonical row for those two
``status_completed``         (one row per           gestures, collapsed to at most one
                             ``(user, item,         per user — see "One gesture per
                             event_type)``)         user" below.
Backlog intent               ``library_entries``    Restricted to the three statuses
                             (non-``completed``,    that never emit an event — a
                             and with no            ``completed`` row is deliberately
                             ``status_completed``   *excluded*, it is already counted
                             of its own in the      as ``status_completed`` — **and**
                             window)                to (user, item) pairs with no
                                                    ``status_completed`` event of their
                                                    own in the window. The status
                                                    filter alone is not enough after a
                                                    cycle — see "One gesture per user"
                                                    below.
Rating edit                  ``user_ratings``       Restricted to edits that happened
                             (edited *after* its    strictly after the row's own event
                             own event)             (``updated_at > created_at`` **and**
                                                    ``updated_at > event.created_at``,
                                                    or no event at all). The edit that
                                                    *creates* the event is already
                                                    counted by contribution 1.
============================ ====================== ==================================

The second half of that last condition is not redundant, and the first pass of
this feature got it wrong: ``updated_at > created_at`` alone also matches the
``PUT {}`` → ``PUT {"score": 4}`` sequence above, scoring a single action as
both a creation (3.0) and an edit (1.0). Comparing against the *event's*
timestamp rather than the row's is what separates "I gave this rating content
just now" from "I came back later and changed it". Both cases are pinned by
``TestNoDoubleCounting`` in ``tests/test_trending.py``.

Exclusions: a review hidden by moderation (``user_ratings.is_hidden``) never
contributes — neither through its ``rating_created`` event nor through a
re-rating — because a hidden review must not push anything into trending.

One gesture per user (issue #30)
--------------------------------
The partition above is stated per *kind of row*, and that is not enough on its
own: the ``completed`` → ``dropped`` → ``completed`` toggle leaks through it
twice, in two different ways.

**Leak 1 — several events for the same pair.** ``activity_events`` is the one
of the three tables that can hold several rows for the same user and the same
item. ``library_entries`` and ``user_ratings`` cannot: ``uq_library_entry_item``
and ``uq_user_rating_item`` are both ``(user_id, item_type, item_id)``, so
contributions 2 and 3 are one row per (user, item) by construction — the toggle
*moves* the library row, it does not add one. ``activity_events`` has no such
key for ``status_completed``: its dedup key ``uq_activity_events_rating_id``
only constrains ``rating_created`` (``status_completed`` rows carry
``rating_id NULL``, and Postgres allows any number of NULLs in a unique
constraint). So every lap back into ``completed`` writes another event, without
a ceiling.

Contribution 1 therefore groups by ``(user_id, item_id, event_type)`` and emits
**one** row per group.

**Leak 2 — the same pair counted by two different contributions.** Excluding
``completed`` from contribution 2 keeps the two apart *during* the transition,
but a cycle does not end where it started: after ``completed → dropped`` the
library row sits on ``dropped``, a status that counts, while the
``status_completed`` event written on the way in is still inside the window. The
same user then pays twice for one back-and-forth — 2.0 for the event plus 0.5
for the intent — and half as many items as the threshold were enough for a
single account to take over a whole type.

Contribution 2 therefore adds a correlated ``NOT EXISTS``: a library row is
dropped from the intent side when the **same user** has a ``status_completed``
event for the **same item** inside the window. Two details are load-bearing.
The correlation is by (user, item), not by item: another user's completion says
nothing about this user's intent. And the subquery looks only at
``status_completed``: a ``rating_created`` event must not erase backlog intent,
which is a genuinely different gesture, counted on its own by contribution 1.
When both exist the stronger one survives, which is the completion.

Together the two make the invariant hold again as stated above — at most one
gesture per ``(user, item, kind of gesture)`` inside the window, whichever
status the cycle happens to stop on.

Both are read-side fixes on purpose: the writer and the feed keep behaving
exactly as before (each transition into ``completed`` stays its own narrative
fact in ``GET /feed``); what changes is only how trending *counts* it.

Which timestamp survives the collapse matters, because the surviving row is
what the decay is applied to. The group keeps ``MAX(created_at)`` **inside the
window**: the most recent lap is the gesture the user actually just made, and
"this user has this item completed right now" is the honest reading of the
collapsed group. Keeping the oldest would let a stale event from the window's
edge speak for a gesture made minutes ago, and understate live activity.

``total_gestures`` is computed over the same already-collapsed rows, so the
``TRENDING_MIN_ACTIVITY`` threshold counts de-duplicated gestures too —
counting raw rows there would leave the manipulation vector wide open and make
the fix cosmetic.

Decay
-----
Every contribution is weighted by an explicit exponential decay,
``0.5 ** (age / half_life)``: a gesture exactly one half-life old is worth half
of a gesture made right now. The half-lives per period live in
``backlogg/trending/service.py`` next to the windows they belong to.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, case, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, aliased

from backlogg.feed.models import ActivityEvent
from backlogg.library.models import LibraryEntry
from backlogg.ratings.models import UserRating
from backlogg.ratings.repository import ITEM_MODELS

__all__ = [
    "EVENT_WEIGHTS",
    "INTENT_WEIGHTS",
    "RATING_EDIT_WEIGHT",
    "activity_scores",
    "get_items_by_ids",
]

# Relative weight of each distinct user gesture. Ratings weigh most (the user
# formed an opinion), completions next (the user finished the item), backlog
# intent least (a click). ``dropped`` still counts — trending measures
# attention, not approval — but it is the cheapest gesture there is.
#
# Kept as three separate tables rather than one, because their keys are three
# different things and only the first two are column values:
# ``activity_events.event_type``, ``library_entries.status``, and a weight that
# corresponds to no column at all.

# Keys are ``activity_events.event_type`` values (see ACTIVITY_EVENT_TYPES).
EVENT_WEIGHTS: dict[str, float] = {
    "rating_created": 3.0,
    "status_completed": 2.0,
}

# Keys are ``library_entries.status`` values — and deliberately only the three
# that never produce an activity_events row, which is what lets this table
# contribute without double counting. ``completed`` is absent on purpose.
INTENT_WEIGHTS: dict[str, float] = {
    "want": 1.0,
    "in_progress": 1.5,
    "dropped": 0.5,
}

# Not an event type and not a status: the weight of editing an existing rating,
# a gesture that leaves no row of its own anywhere.
RATING_EDIT_WEIGHT = 1.0


def _weight_case(column, weights: dict[str, float]):
    """``CASE`` mapping a status/event-type column to its weight."""
    return case(
        *[(column == key, literal(weight, Float)) for key, weight in weights.items()],
        else_=literal(0.0, Float),
    )


def _decay(ts_column, now: datetime, half_life_seconds: float):
    """Exponential time decay: ``0.5 ** (age / half_life)``.

    Explicit and testable by construction — a gesture one half-life old is
    worth exactly half of one made at ``now``, two half-lives a quarter, and so
    on. This is what keeps a burst of six-day-old activity from outranking
    fresher, smaller activity.
    """
    age_seconds = func.extract("epoch", literal(now, DateTime(timezone=True)) - ts_column)
    return func.power(
        literal(0.5, Float),
        cast(age_seconds, Float) / literal(half_life_seconds, Float),
    )


async def activity_scores(
    db: AsyncSession,
    *,
    item_type: str,
    since: datetime,
    now: datetime,
    half_life_seconds: float,
    limit: int,
) -> tuple[int, list[tuple[int, float]]]:
    """Return ``(total_gestures, [(item_id, score), ...])`` for one item type.

    ``total_gestures`` is the number of distinct gestures for the whole type
    inside the window — the service compares it against
    ``TRENDING_MIN_ACTIVITY`` to decide whether the local signal is worth
    serving. It counts the same de-duplicated rows that feed the score (see the
    module docstring: one gesture per ``(user, item, event_type)``), never the
    raw ``activity_events`` rows. It is computed with a window function over
    the aggregate (``sum(count(*)) OVER ()``) so the truncation to the top
    ``limit`` items cannot distort it, and so the whole thing stays a single
    round trip.

    The rows are ordered by decayed score descending; ``item_id`` breaks ties
    so the ordering is deterministic.
    """
    # ── Contribution 1: the two feed-worthy creation events ──────────────────
    # LEFT JOIN to the rating so a hidden review's event drops out.
    # status_completed rows have rating_id NULL and are unaffected.
    #
    # GROUP BY collapses the completed → dropped → completed toggle (issue #30)
    # to a single gesture per user and item: ``activity_events`` is the only
    # one of the three tables that can hold several rows for the same pair.
    # The surviving timestamp is the most recent lap inside the window, which
    # is the gesture the user actually just made — the rationale is in the
    # module docstring. ``event_type`` is a grouping key, so the weight CASE
    # over it is well defined for the group.
    events = (
        select(
            ActivityEvent.item_id.label("item_id"),
            _weight_case(ActivityEvent.event_type, EVENT_WEIGHTS).label("weight"),
            func.max(ActivityEvent.created_at).label("ts"),
        )
        .outerjoin(UserRating, ActivityEvent.rating_id == UserRating.id)
        .where(
            ActivityEvent.item_type == item_type,
            ActivityEvent.created_at >= since,
            (ActivityEvent.rating_id.is_(None)) | (UserRating.is_hidden.is_(False)),
        )
        .group_by(
            ActivityEvent.user_id,
            ActivityEvent.item_id,
            ActivityEvent.event_type,
        )
    )

    # ── Contribution 2: backlog intent that never emits an event ─────────────
    # No grouping needed: ``uq_library_entry_item`` is (user_id, item_type,
    # item_id), so a user has at most one row per item however many times the
    # status is toggled — the toggle moves the row, it does not add one.
    #
    # The NOT EXISTS is what keeps this contribution disjoint from the first
    # one *after a cycle* (issue #30). Excluding the ``completed`` status is
    # not enough: ``completed → dropped`` leaves the row on a counting status
    # while the ``status_completed`` event written on the way in is still
    # inside the window, so the same user would pay 2.0 for the event plus 0.5
    # for the intent. Correlated by (user, item) — not by item alone, because
    # another user's completion says nothing about this user's intent — and
    # restricted to ``status_completed``: a ``rating_created`` event must not
    # erase backlog intent, which is a different, legitimate gesture counted on
    # its own.
    completed_by_the_same_user = (
        select(literal(1))
        .select_from(ActivityEvent)
        .where(
            ActivityEvent.user_id == LibraryEntry.user_id,
            ActivityEvent.item_type == LibraryEntry.item_type,
            ActivityEvent.item_id == LibraryEntry.item_id,
            ActivityEvent.event_type == "status_completed",
            ActivityEvent.created_at >= since,
        )
        .correlate(LibraryEntry)
        .exists()
    )
    intent = select(
        LibraryEntry.item_id.label("item_id"),
        _weight_case(LibraryEntry.status, INTENT_WEIGHTS).label("weight"),
        LibraryEntry.updated_at.label("ts"),
    ).where(
        LibraryEntry.item_type == item_type,
        LibraryEntry.status.in_(INTENT_WEIGHTS),
        LibraryEntry.updated_at >= since,
        ~completed_by_the_same_user,
    )

    # ── Contribution 3: an edit that happened after the row's own event ──────
    # The join is to the rating's own event, and it cannot multiply rows:
    # ``uq_activity_events_rating_id`` allows at most one event per rating.
    # No grouping needed here either: ``uq_user_rating_item`` is (user_id,
    # item_type, item_id), so re-rating overwrites one row instead of adding.
    #
    # Both conditions are needed, and neither implies the other:
    #
    # - ``updated_at > created_at`` rules out a freshly inserted row (an
    #   INSERT leaves the two equal, since the ``set_updated_at_user_ratings``
    #   trigger is BEFORE UPDATE only).
    # - ``event IS NULL OR updated_at > event.created_at`` rules out the edit
    #   that *created* the event. ``rate_item`` only writes the event once the
    #   rating has content, so ``PUT {}`` then ``PUT {"score": 4}`` produces a
    #   row whose event was born in the second call: that call is already
    #   counted by contribution 1 and must not be counted again here.
    event_of_rating = aliased(ActivityEvent)
    rerating = (
        select(
            UserRating.item_id.label("item_id"),
            literal(RATING_EDIT_WEIGHT, Float).label("weight"),
            UserRating.updated_at.label("ts"),
        )
        .outerjoin(event_of_rating, event_of_rating.rating_id == UserRating.id)
        .where(
            UserRating.item_type == item_type,
            UserRating.is_hidden.is_(False),
            UserRating.updated_at >= since,
            UserRating.updated_at > UserRating.created_at,
            (event_of_rating.id.is_(None)) | (UserRating.updated_at > event_of_rating.created_at),
        )
    )

    gestures = union_all(events, intent, rerating).subquery()

    score = func.sum(gestures.c.weight * _decay(gestures.c.ts, now, half_life_seconds))
    stmt = (
        select(
            gestures.c.item_id,
            score.label("score"),
            func.sum(func.count()).over().label("total_gestures"),
        )
        .group_by(gestures.c.item_id)
        .order_by(score.desc(), gestures.c.item_id.asc())
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0, []
    total_gestures = int(rows[0].total_gestures)
    return total_gestures, [(int(row.item_id), float(row.score)) for row in rows]


async def get_items_by_ids(
    db: AsyncSession, item_type: str, item_ids: list[int]
) -> dict[int, DeclarativeBase]:
    """Resolve catalog rows for a batch of ids — one query, never one per item.

    Returned as a dict so the caller can re-apply the score ordering. Ids with
    no catalog row (the activity tables are polymorphic and carry no FK) are
    simply absent: an item whose catalog row is gone is dropped, not an error.
    """
    if not item_ids:
        return {}
    model = ITEM_MODELS[item_type]
    result = await db.execute(select(model).where(model.id.in_(item_ids)))
    return {row.id: row for row in result.scalars().all()}
