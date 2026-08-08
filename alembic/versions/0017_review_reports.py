"""review_reports — users flag reviews; admin moderation queue

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # review_reports — one report per (reporter, reported review).
    # ``rating_id`` references user_ratings.id (a "review" is a UserRating row);
    # both FKs cascade so reports disappear with the reporter or the review.
    # ``status`` is an enum-like plain string constrained by a CHECK, matching
    # how account_tokens.purpose is modelled (no PostgreSQL ENUM type).
    op.create_table(
        "review_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reporter_id", sa.BigInteger(), nullable=False),
        sa.Column("rating_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rating_id"], ["user_ratings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reporter_id", "rating_id", name="uq_review_report_pair"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_review_reports_status"),
    )
    op.create_index("idx_review_reports_status", "review_reports", ["status"])


def downgrade() -> None:
    op.drop_index("idx_review_reports_status", table_name="review_reports")
    op.drop_table("review_reports")
