"""library_logs — activity log entries (rewatch/replay/reread sessions)

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 52 (activity_log_entries): decoupled from user_ratings so a user
    # can log multiple dated sessions (rewatch/replay/reread) of the same item
    # without touching their score/review. Deliberately no
    # UniqueConstraint(user_id, item_type, item_id) — unlike user_ratings /
    # library_entries, multiple rows per (user, item) are allowed here.
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


def downgrade() -> None:
    op.drop_table("library_logs")
