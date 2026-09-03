"""seed_targets — the enumerated TMDB catalog target list

Feature 86 (tmdb_discover_quality_seeding) splits *enumeration* from
*hydration*.  Enumeration answers "which items clear the quality threshold"
with ~3.600 cheap ``/discover`` requests; hydration then costs one detail
request per item.  This table holds the enumeration's answer so hydration can
be resumed, ordered and audited independently of it.

It is what replaces ``sync_cursors`` for MOVIE and SERIES.  An offset into
``/movie/popular`` resumes nothing — the listing reorders itself while being
paginated — whereas with the target list persisted "what is left to do" is a
difference against the catalog (``LEFT JOIN external_ids ... WHERE NULL``),
which converges by construction whatever way a run died.

Column notes:

- ``vote_count``/``release_year`` are what ``/discover`` reported at
  enumeration time.  They are free (they travel in the payload) and give the
  hydration a notoriety order, so an interrupted seeding run leaves the best
  of the catalog in rather than an arbitrary slice.
- ``attempts``/``last_attempt_at``/``unreachable_at`` are the convergence
  guard.  A target can legitimately never yield an ``external_ids`` row, for
  two unrelated reasons: its ``(source, external_id)`` pair being already
  claimed by another item (at the time of this migration ``uq_external_id``
  was global over ``(source, external_id)`` while TMDB numbers movies, series
  and people in independent sequences, so *any* other type could claim the id
  — migration ``0036`` narrows that to a collision within the same type, see
  issue #20), and an enumerated id can simply be 404 at TMDB by the time it is
  hydrated.  Both would keep the pending set permanently above zero, which
  would disable the ``last_synced_at`` refresh rotation and stop the backfill
  loop from ever terminating.  ``unreachable_at`` records the 404 (a
  definitive answer, stamped on the first observation) and ``attempts``
  counts *conclusive* passes so a target that keeps resolving without ever
  linking is retired after ``TMDB_SEED_MAX_ATTEMPTS``.  Neither is forgotten:
  both are still counted and reported as ``stuck``.
- The unique key is ``(item_type, source, external_id)``, so the same TMDB id
  can legitimately be a movie target and a series target.

No existing table is touched: ``sync_cursors`` keeps its MOVIE/SERIES rows,
which simply stop being read (dropping them would make a downgrade of this
migration land on a catalog the old code could not resume).

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seed_targets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("vote_count", sa.Integer(), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unreachable_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "source", "external_id", name="uq_seed_target"),
    )
    # Work-order index: every read of this table filters by (item_type, source)
    # and orders by attempts first.
    op.create_index(
        "idx_seed_targets_work_order",
        "seed_targets",
        ["item_type", "source", "attempts"],
    )
    # Reuses trigger_set_updated_at() defined in 0001.
    op.execute(
        """
        CREATE TRIGGER set_updated_at_seed_targets
        BEFORE UPDATE ON seed_targets
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_seed_targets ON seed_targets;")
    op.drop_index("idx_seed_targets_work_order", table_name="seed_targets")
    op.drop_table("seed_targets")
