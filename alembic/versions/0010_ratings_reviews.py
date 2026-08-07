"""ratings_reviews — user_ratings and review_likes

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-06

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── user_ratings ──────────────────────────────────────────────
    op.create_table(
        "user_ratings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_rating_item"),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)", name="ck_user_ratings_score_range"
        ),
    )
    op.create_index("idx_user_ratings_item", "user_ratings", ["item_type", "item_id"])
    op.create_index("idx_user_ratings_user", "user_ratings", ["user_id"])

    # ── trigger for user_ratings — reuses trigger_set_updated_at() from 0001 ──
    op.execute(
        """
        CREATE TRIGGER set_updated_at_user_ratings
        BEFORE UPDATE ON user_ratings
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── review_likes ──────────────────────────────────────────────
    op.create_table(
        "review_likes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("rating_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rating_id"], ["user_ratings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "rating_id", name="uq_review_like"),
    )
    op.create_index("idx_review_likes_rating", "review_likes", ["rating_id"])
    op.create_index("idx_review_likes_user", "review_likes", ["user_id"])


def downgrade() -> None:
    op.drop_table("review_likes")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_user_ratings ON user_ratings;")
    op.drop_table("user_ratings")
