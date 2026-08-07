"""follows — unidirectional follow relationships between users

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("follower_id", sa.BigInteger(), nullable=False),
        sa.Column("followed_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["followed_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),
    )
    op.create_index("idx_follows_follower", "follows", ["follower_id"])
    op.create_index("idx_follows_followed", "follows", ["followed_id"])


def downgrade() -> None:
    op.drop_index("idx_follows_followed", table_name="follows")
    op.drop_index("idx_follows_follower", table_name="follows")
    op.drop_table("follows")
