"""sync_watermarks — where each incremental mechanism left off

Feature 88 (catalog_incremental_updates) stops maintaining the catalog by
re-walking full listings and starts asking every source *what changed since
last time*.  That question needs a persisted answer to "last time", and the
two state tables that exist cannot give it:

- ``sync_cursors`` holds a numeric offset into a listing.  It answers "how far
  down the page am I", not "up to which instant have I already seen the
  world", and its ``updated_at`` is a row-touch timestamp rather than a
  cut-off.
- ``seed_targets`` is a work list *by difference* against the catalog.  It
  converges without any cursor precisely because it carries no notion of time,
  which is why it cannot express "ask TMDB for the changes of the last N
  days".

Neither is touched by this migration: both keep their rows and their meaning.

The key is ``(source, kind, item_type)``
----------------------------------------

One row per source *and* mechanism *and* content type, because those advance
and fail independently.  The rows the incremental writes are:

    TMDB / DAILY_ID_EXPORT / MOVIE   -> date of the export file processed
    TMDB / DAILY_ID_EXPORT / SERIES  -> date of the export file processed
    TMDB / CHANGES        / MOVIE    -> last instant covered
    TMDB / CHANGES        / SERIES   -> last instant covered
    IGDB / CREATED_AT     / GAME     -> last ``created_at`` covered
    IGDB / UPDATED_AT     / GAME     -> last ``updated_at`` covered
    OPEN_LIBRARY / MONTHLY_DUMP / BOOK -> edition of the dump diffed

Keying by ``source`` alone would collapse the two TMDB mechanisms, and
``/changes`` can be days behind while the daily export is current.  Keying by
``(source, kind)`` would collapse movies and series, which are two separate
passes against two separate endpoints.

``item_type`` is ``NOT NULL`` even for mechanisms that serve a single type.
This is not tidiness: Postgres treats NULLs as distinct inside a unique index,
so a nullable component of the primary key would make ``INSERT ... ON CONFLICT
DO UPDATE`` never match and every run would append a duplicate row instead of
advancing the watermark.

Two columns, not one
--------------------

``last_run_at`` and ``cursor_value`` are not redundant.  A run that queried up
to instant *T* and finished at *T+9min* must resume at *T* or lose those nine
minutes of changes; and the TMDB daily export is published around 08:00 UTC,
so a run at 00:10 UTC processes *yesterday's* file.  They are not even the
same type: an instant for ``CHANGES``/IGDB, a file date for
``DAILY_ID_EXPORT``, a dump edition for ``MONTHLY_DUMP`` — hence ``TEXT``
(ISO-8601 by convention, parsed by whoever wrote it) rather than a
``timestamptz`` that would force a fake midnight on a file date.

``last_run_at`` is the operational half: freshness ("did the incremental run
last night?") and the input to the 14-day gap check of ``/changes``, whose
history TMDB only keeps for 14 days.

``cursor_value`` is nullable so that "ran but produced no usable cut-off yet"
is expressible and distinct from "never ran", which is the absence of the row.

The ``updated_at`` trigger reuses ``trigger_set_updated_at()`` from migration
0001, same as ``seed_targets`` (0035).

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_watermarks",
        sa.Column("source", sa.String(length=20), nullable=False),
        # 40 chars: the longest mechanism name in use is DAILY_ID_EXPORT (15);
        # the headroom is for mechanisms phases B and C have not named yet.
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        # Opaque to the persistence layer on purpose — see the module
        # docstring: its format belongs to the mechanism that wrote it.
        sa.Column("cursor_value", sa.Text(), nullable=True),
        sa.Column(
            "last_run_at",
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
        sa.PrimaryKeyConstraint("source", "kind", "item_type", name="pk_sync_watermarks"),
    )
    # No secondary index: the table holds one row per mechanism (seven of them
    # as of this feature) and every read is a primary-key lookup.  An index
    # here would cost writes and buy nothing a sequential scan of seven rows
    # does not already give.
    op.execute(
        """
        CREATE TRIGGER set_updated_at_sync_watermarks
        BEFORE UPDATE ON sync_watermarks
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_sync_watermarks ON sync_watermarks;")
    op.drop_table("sync_watermarks")
