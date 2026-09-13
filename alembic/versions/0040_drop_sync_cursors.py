"""drop sync_cursors — the offset walk it served no longer exists

The table held one row per item type with the offset the next nightly run had
to resume the external listing from.  All four types left that mechanism, each
one replaced by the refresh rotation (``get_stale_catalog_external_ids``, which
picks the catalog's oldest ``last_synced_at``) plus, for the three types with a
target list, the ``seed_targets`` difference: movies and series in feature 86,
games in feature 90 and books in issue #27.  With books gone no code path reads
or writes the table, so what is left is four rows that only invite someone to
wire a cursor back in.

This is not a space measure and should not be sold as one: the table was four
rows and 64 kB.  It is the removal of a dead mechanism.

The downgrade does not restore the offsets, and that is not a loss
----------------------------------------------------------------

It recreates the table empty, with its original shape.  The values are not
recoverable and do not need to be: nothing reads them, so an empty table and
the old one are indistinguishable to every live code path.  Should a rollback
ever go far enough back to reach code that *did* read the cursor, that code
resumes from 0 when the row is absent (the old ``get_sync_offset`` returned 0
for a missing row) — which is exactly the state an empty table expresses.  The
cost of that is a nightly run starting at the top of a ranking, which is what
the wraparound did on its own every time it completed a lap.

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``IF EXISTS`` rather than ``op.drop_table``: this runs against production
    # on deploy, and a re-run (or a database where the table was already
    # dropped by hand) must not abort the whole migration chain over a table
    # nobody uses.
    op.execute("DROP TABLE IF EXISTS sync_cursors;")


def downgrade() -> None:
    # Same shape as migration 0008 created it, empty.  See the module
    # docstring for why the offsets are not restored.
    op.create_table(
        "sync_cursors",
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("next_offset", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("item_type"),
    )
