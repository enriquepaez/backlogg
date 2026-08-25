"""catalog_search — add rating_internal to the SELECT of all 4 sub-queries

Recreates the catalog_search materialized view (same DROP + CREATE pattern
already used by 0028_catalog_search_punctuation_normalization) so every row
also carries rating_internal — the 4 base tables (movies/series/books/games)
already have the column; this just exposes it through the view for the
list/grid schemas (feature 69, rating_internal_list_exposure). The
search_vector expression itself is unchanged from 0028.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEARCH_VECTOR_EXPR = (
    "to_tsvector('simple', "
    "title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\\s]', '', 'g') || "
    "' ' || COALESCE(overview, ''))"
)


def _create_view(with_rating_internal: bool) -> None:
    rating_internal_col = "rating_internal," if with_rating_internal else ""
    op.execute(
        f"""
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
            {rating_internal_col}
            {_SEARCH_VECTOR_EXPR} AS search_vector
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
            {rating_internal_col}
            {_SEARCH_VECTOR_EXPR}
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
            {rating_internal_col}
            {_SEARCH_VECTOR_EXPR}
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
            {rating_internal_col}
            {_SEARCH_VECTOR_EXPR}
        FROM games
        """
    )

    op.execute("CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector)")
    op.execute("CREATE INDEX idx_catalog_search_type ON catalog_search (item_type)")
    op.execute("CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id)")


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
    _create_view(with_rating_internal=True)
    op.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
    _create_view(with_rating_internal=False)
    op.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search")
