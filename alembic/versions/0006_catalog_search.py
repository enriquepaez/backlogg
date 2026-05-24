"""catalog_search — materialized view for cross-type full-text search

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW catalog_search AS
        SELECT
            id,
            'MOVIE'         AS item_type,
            slug,
            title,
            overview,
            poster_url,
            release_date,
            rating_external,
            to_tsvector('simple', title || ' ' || COALESCE(overview, '')) AS search_vector
        FROM movies
        UNION ALL
        SELECT
            id,
            'SERIES',
            slug,
            title,
            overview,
            poster_url,
            first_air_date,
            rating_external,
            to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
        FROM series
        UNION ALL
        SELECT
            id,
            'BOOK',
            slug,
            title,
            overview,
            poster_url,
            first_publish_date,
            rating_external,
            to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
        FROM books
        UNION ALL
        SELECT
            id,
            'GAME',
            slug,
            title,
            overview,
            poster_url,
            release_date,
            rating_external,
            to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
        FROM games
        """
    )

    op.execute("CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector)")
    op.execute("CREATE INDEX idx_catalog_search_type ON catalog_search (item_type)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
