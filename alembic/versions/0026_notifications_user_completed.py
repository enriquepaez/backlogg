"""notifications_user_completed — add user_completed to notifications.type

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 55 (notifications_event_types_expansion): widen
    # notifications.type to allow 'user_completed' — generated for each direct
    # follower when a followed user's status_completed feed event (feature 54)
    # fires. No column change, only the CHECK constraint (drop + recreate),
    # same style as 0024_rating_score_granularity.py.
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        "type IN ('new_follower', 'review_like', 'user_completed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        "type IN ('new_follower', 'review_like')",
    )
