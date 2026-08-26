"""book_isbn_field — add isbn to books

Feature 71: Open Library already returns ``isbn`` in the same
``search.json`` call used today (field-set
``key,title,author_name,first_publish_year,cover_i,subject,isbn``), but it
was discarded by ``book_to_dict``. This just persists it — no new external
call.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("books", sa.Column("isbn", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "isbn")
