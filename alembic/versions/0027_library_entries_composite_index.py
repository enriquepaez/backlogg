"""library_entries_composite_index — add (user_id, status) index

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 60 (library_entries_composite_index): production audit2
    # (2026-08-19) flagged that the hottest read path,
    # GET /users/{username}/library?status=completed, filters by user_id and
    # then status within each branch of the repository's UNION ALL, but only
    # idx_library_entries_user (user_id) and idx_library_entries_item
    # (item_type, item_id) existed — neither covers the (user_id, status)
    # pair.
    op.create_index("idx_library_entries_user_status", "library_entries", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_library_entries_user_status", table_name="library_entries")
