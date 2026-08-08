"""notifications — social notifications (new_follower, review_like)

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_read",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("type IN ('new_follower', 'review_like')", name="ck_notifications_type"),
    )
    # Recipient feed: newest first — composite index on (recipient_id, created_at DESC).
    op.create_index(
        "idx_notifications_recipient_created",
        "notifications",
        ["recipient_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
