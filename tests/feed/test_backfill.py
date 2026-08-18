"""Test for the activity_events backfill (alembic/versions/0025_activity_events.py).

Loads the migration module by path (same pattern as tests/test_backfill_sync.py
for scripts/backfill_sync.py — alembic/versions module names are not valid
Python identifiers, so a regular import doesn't work) and executes its
``BACKFILL_RATING_CREATED_SQL`` constant directly against a hand-seeded
"pre-migration" state: a user_ratings row inserted without going through
backlogg/ratings/service.py (which is what generates the event on the normal
write path), simulating data that existed before this migration ran. This
proves the exact SQL statement used in ``upgrade()`` populates activity_events
correctly, without needing to invoke Alembic itself.
"""

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from backlogg.feed.models import ActivityEvent
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.users.repository import create_user

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "alembic"
    / "versions"
    / "0025_activity_events.py"
)
_spec = importlib.util.spec_from_file_location("activity_events_migration", _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
sys.modules["activity_events_migration"] = _migration
_spec.loader.exec_module(_migration)


def _movie_data(slug: str) -> dict:
    return {
        "title": "Backfill Movie",
        "original_title": "Backfill Movie",
        "slug": slug,
        "overview": "overview",
        "release_date": date(2020, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


async def test_backfill_sql_creates_rating_created_events_for_existing_ratings(db):
    user = await create_user(
        db,
        {
            "username": "backfill-user-1",
            "email": "backfill-user-1@example.com",
            "password_hash": "hash",
            "display_name": "Backfill User",
        },
    )
    movie = await upsert_movie(db, _movie_data("backfill-movie-1"))

    # Simulate a rating that existed before this migration: upsert_rating alone
    # (no create_rating_event call, unlike the current write path in
    # backlogg/ratings/service.py::rate_item).
    rating = await upsert_rating(
        db,
        user_id=user.id,
        item_type="MOVIE",
        item_id=movie.id,
        score=4,
        review_text="pre-existing",
    )
    old_created_at = datetime.now(UTC) - timedelta(days=100)
    rating.created_at = old_created_at
    await db.flush()

    result = await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating.id))
    assert result.scalar_one_or_none() is None

    await db.execute(text(_migration.BACKFILL_RATING_CREATED_SQL))
    await db.flush()

    result = await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating.id))
    event = result.scalar_one()
    assert event.event_type == "rating_created"
    assert event.user_id == user.id
    assert event.item_type == "MOVIE"
    assert event.item_id == movie.id
    assert event.created_at == old_created_at


async def test_backfill_sql_skips_ratings_without_score_or_review_text(db):
    user = await create_user(
        db,
        {
            "username": "backfill-user-2",
            "email": "backfill-user-2@example.com",
            "password_hash": "hash",
            "display_name": "Backfill User 2",
        },
    )
    movie = await upsert_movie(db, _movie_data("backfill-movie-2"))

    # A rating row with no content at all shouldn't happen via the API today,
    # but the backfill query is defensive about it regardless.
    rating = await upsert_rating(
        db, user_id=user.id, item_type="MOVIE", item_id=movie.id, score=None, review_text=None
    )

    await db.execute(text(_migration.BACKFILL_RATING_CREATED_SQL))
    await db.flush()

    result = await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating.id))
    assert result.scalar_one_or_none() is None


async def test_backfill_sql_is_idempotent_on_rerun(db):
    user = await create_user(
        db,
        {
            "username": "backfill-user-3",
            "email": "backfill-user-3@example.com",
            "password_hash": "hash",
            "display_name": "Backfill User 3",
        },
    )
    movie = await upsert_movie(db, _movie_data("backfill-movie-3"))
    rating = await upsert_rating(
        db,
        user_id=user.id,
        item_type="MOVIE",
        item_id=movie.id,
        score=None,
        review_text="text only",
    )

    await db.execute(text(_migration.BACKFILL_RATING_CREATED_SQL))
    await db.execute(text(_migration.BACKFILL_RATING_CREATED_SQL))
    await db.flush()

    result = await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating.id))
    events = result.scalars().all()
    assert len(events) == 1
