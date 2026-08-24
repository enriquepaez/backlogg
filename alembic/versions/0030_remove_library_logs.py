"""remove_library_logs — drop the activity log domain (feature 64)

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 64: the activity log domain (feature 52, dated rewatch/replay/
    # reread sessions decoupled from ratings) is removed entirely as a product
    # decision — it added complexity without enough value. Reviews/ratings
    # (user_ratings) are untouched; this only drops library_logs, created in
    # 0023_library_logs.py.
    op.drop_table("library_logs")


def downgrade() -> None:
    # Recreates library_logs exactly as it was defined in
    # 0023_library_logs.py, so downgrading restores the original schema.
    op.create_table(
        "library_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("logged_on", sa.Date(), nullable=False),
        sa.Column("rewatch", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_library_logs_item", "library_logs", ["item_type", "item_id"])
    op.create_index("idx_library_logs_user", "library_logs", ["user_id"])
