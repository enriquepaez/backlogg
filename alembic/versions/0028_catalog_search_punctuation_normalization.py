"""catalog_search — normalize punctuation in title for full-text search

Recreates the catalog_search materialized view so search_vector indexes an
additional punctuation-stripped variant of the title (spaces preserved as
word separators). Postgres' `simple` dictionary tokenizes hyphenated/
punctuated words (e.g. "Spider-Man") into the punctuated lexeme plus its
halves, but never into the concatenated form ("spiderman") — so a user
query without punctuation ("Spiderman") never matched a title with
punctuation ("Spider-Man"). See issues_list.json, issue id 13.

overview is left unnormalized — the reported bug is about titles only.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEARCH_VECTOR_EXPR = (
    "to_tsvector('simple', "
    "title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\\s]', '', 'g') || "
    "' ' || COALESCE(overview, ''))"
)

_SEARCH_VECTOR_EXPR_PREVIOUS = "to_tsvector('simple', title || ' ' || COALESCE(overview, ''))"


def _create_view(search_vector_expr: str) -> None:
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
            {search_vector_expr} AS search_vector
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
            {search_vector_expr}
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
            {search_vector_expr}
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
            {search_vector_expr}
        FROM games
        """
    )

    op.execute("CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector)")
    op.execute("CREATE INDEX idx_catalog_search_type ON catalog_search (item_type)")
    op.execute("CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id)")


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
    _create_view(_SEARCH_VECTOR_EXPR)
    op.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
    _create_view(_SEARCH_VECTOR_EXPR_PREVIOUS)
    op.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search")
