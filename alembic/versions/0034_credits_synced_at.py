"""credits_synced_at — mark items whose credits were already looked up

Feature 85 (backfill_credits_targeted): the targeted backfill picks its work
list with ``LEFT JOIN credits ... WHERE NULL``.  That query alone would hand
back the same items on every run for a legitimate reason — a TMDB movie with
an empty ``cast``/``crew``, an Open Library work with no resolvable author —
because "no credits" and "credits never fetched" look identical from the
credits table.

``credits_synced_at`` is the discriminator: the targeted mode stamps it after
a *successful* credits fetch, whether or not that fetch produced rows, so an
item that genuinely has nothing to persist is visited exactly once.  A failed
fetch stamps nothing and is retried by the next run.

Nullable and mirroring the existing ``last_synced_at`` (timestamptz), so no
backfill of the column itself is needed: NULL means "never looked up", which
is the correct starting state for every row already in the catalog.

games is out of scope (it has no people-credit ingestion at all), so the
column is only added to the three tables that do.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("movies", "series", "books")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("credits_synced_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "credits_synced_at")
