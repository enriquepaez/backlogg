"""catalog_search — unique index on (item_type, id) for REFRESH CONCURRENTLY

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-26

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_catalog_search_type_id")
