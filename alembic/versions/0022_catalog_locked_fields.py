"""catalog_locked_fields — add locked_fields to movies/series/books/games

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("movies", "series", "books", "games")


def upgrade() -> None:
    # Feature 49 (catalog_manual_edit): per-field admin lock. Column names
    # manually edited via PATCH /v1/admin/{type}/{slug} are appended here so
    # the nightly sync (backlogg/scheduler/jobs.py -> upsert_*) skips them on
    # the next upsert instead of overwriting the admin's edit.
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "locked_fields",
                postgresql.ARRAY(sa.String()),
                server_default="{}",
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "locked_fields")
