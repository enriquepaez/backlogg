"""rating_score_granularity — user_ratings.score half-star (0.5) steps

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 53 (rating_score_granularity): widen user_ratings.score from a
    # whole-star Integer (1-5) to half-star steps (1.0, 1.5, ..., 5.0). The
    # existing integer values (1-5) are a strict subset of the new domain, so
    # no backfill is needed — only the column type and CHECK constraint change.
    op.drop_constraint("ck_user_ratings_score_range", "user_ratings", type_="check")
    op.alter_column(
        "user_ratings",
        "score",
        type_=sa.Numeric(2, 1),
        existing_type=sa.Integer(),
        postgresql_using="score::numeric(2,1)",
    )
    op.create_check_constraint(
        "ck_user_ratings_score_range",
        "user_ratings",
        "score IS NULL OR (score >= 1 AND score <= 5 AND score * 2 = FLOOR(score * 2))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_ratings_score_range", "user_ratings", type_="check")
    op.alter_column(
        "user_ratings",
        "score",
        type_=sa.Integer(),
        existing_type=sa.Numeric(2, 1),
        postgresql_using="round(score)::integer",
    )
    op.create_check_constraint(
        "ck_user_ratings_score_range",
        "user_ratings",
        "score IS NULL OR (score >= 1 AND score <= 5)",
    )
