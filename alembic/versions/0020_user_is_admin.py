"""user_is_admin — add admin role flag to users

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Admin role flag. No API endpoint flips this — it is set by hand in the DB
    # by an operator, to avoid a privilege-escalation surface. Consumed by the
    # frontend (apps/web `/admin`) to gate the admin section.
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
