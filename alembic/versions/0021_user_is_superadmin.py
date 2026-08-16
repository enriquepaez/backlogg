"""user_is_superadmin — add superadmin role flag to users

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Superadmin role flag, same pattern as is_admin (0020): no API endpoint
    # flips this — it is set by hand in the DB by an operator, to avoid a
    # privilege-escalation surface. A superadmin is the only role allowed to
    # grant/revoke is_admin on other users (POST /v1/admin/users/{username}/
    # grant-admin and /revoke-admin), so this flag itself stays DB-only.
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
