"""content_moderation — hide reviews (is_hidden) and ban users (is_banned)

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-review moderation flag: a hidden review is excluded from public
    # listings, the feed and the rating aggregates (but the row is preserved).
    op.add_column(
        "user_ratings",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    # Per-user moderation flag: a banned user cannot log in or refresh, and all
    # of their reviews become invisible on the same surfaces as a hidden review.
    op.add_column(
        "users",
        sa.Column(
            "is_banned",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_banned")
    op.drop_column("user_ratings", "is_hidden")
