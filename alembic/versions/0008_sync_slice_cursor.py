"""sync_cursors — persisted per-type offset for slice-based nightly sync

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("sync_cursors")
