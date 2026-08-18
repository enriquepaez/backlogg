"""activity_events — generic feed events (rating_created, status_completed)

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Backfill: one rating_created event per existing user_ratings row that has
# actual content (score and/or review_text). Kept as a module-level constant
# (rather than inline in upgrade()) so tests can execute the exact same
# statement against a hand-seeded "pre-migration" row and assert on the result
# — see tests/feed/test_backfill.py. ON CONFLICT DO NOTHING makes this
# statement itself idempotent (safe to run twice), matching
# uq_activity_events_rating_id.
BACKFILL_RATING_CREATED_SQL = """
    INSERT INTO activity_events (user_id, event_type, item_type, item_id, rating_id, created_at)
    SELECT user_id, 'rating_created', item_type, item_id, id, created_at
    FROM user_ratings
    WHERE score IS NOT NULL OR review_text IS NOT NULL
    ON CONFLICT (rating_id) DO NOTHING
"""


def upgrade() -> None:
    # Feature 54 (feed_event_types_expansion): activity_events is a generic
    # feed-events table so backlogg/feed/repository.py can stop reading
    # user_ratings directly. Today only two event types exist, enforced by a
    # CHECK constraint (plain string, no PostgreSQL ENUM type — same modelling
    # as library_entries.status / user_ratings.score).
    #
    # rating_id is nullable (status_completed events have none) with a UNIQUE
    # constraint — Postgres unique constraints allow multiple NULLs, so this
    # only constrains rating_created rows to at most one event per rating,
    # which is what makes event generation idempotent on repeat rating
    # updates (INSERT ... ON CONFLICT DO NOTHING).
    op.create_table(
        "activity_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("rating_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rating_id"], ["user_ratings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rating_id", name="uq_activity_events_rating_id"),
        sa.CheckConstraint(
            "event_type IN ('rating_created', 'status_completed')",
            name="ck_activity_events_type",
        ),
    )
    op.create_index("idx_activity_events_user", "activity_events", ["user_id", "created_at"])
    op.create_index("idx_activity_events_item", "activity_events", ["item_type", "item_id"])

    # Backfill existing reviews so GET /feed?tab=following doesn't go empty
    # overnight for users who already had reviews before this migration.
    op.execute(BACKFILL_RATING_CREATED_SQL)


def downgrade() -> None:
    op.drop_index("idx_activity_events_item", table_name="activity_events")
    op.drop_index("idx_activity_events_user", table_name="activity_events")
    op.drop_table("activity_events")
