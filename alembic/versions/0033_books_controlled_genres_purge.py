"""books_controlled_genres_purge — drop the folksonomic book genres

Feature 72: book genres used to be derived from Open Library's uncontrolled
``subject`` field (~40 tags per work), which produced 510 distinct labels for
370 ingested books — 397 of them used exactly once ("Triathlon",
"Concentration camps", "Country homes"). They are now derived from the
controlled LCC/DDC classifications, so every persisted label predates the new
vocabulary and has to go.

Book genres are *derived* data: re-ingestion (``scripts/backfill_sync.py
book``) repopulates them from Open Library, so purging is safe. The one
exception is admin-curated data — books whose ``locked_fields`` contains
``genres`` were edited by hand through the backoffice (feature 49) and are
skipped by ``upsert_book``; deleting those joins would destroy work that no
sync can rebuild.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-29

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``locked_fields`` is a text[] column (migration 0022); ``'genres' =
    # ANY(...)`` is the SQL form of the ``locked_fields.contains(["genres"])``
    # check upsert_book performs before re-syncing genres.
    op.execute(
        """
        DELETE FROM book_genres_join
        WHERE book_id IN (
            SELECT id FROM books
            WHERE NOT ('genres' = ANY(locked_fields))
        )
        """
    )
    # Genre rows left with no book at all are pure noise from the old
    # folksonomy. Any genre still referenced by a locked book is kept.
    op.execute(
        """
        DELETE FROM book_genres bg
        WHERE NOT EXISTS (
            SELECT 1 FROM book_genres_join j WHERE j.genre_id = bg.id
        )
        """
    )


def downgrade() -> None:
    # Intentional no-op. This migration deletes derived data and keeps no
    # copy of it, so there is nothing to restore: raising here would only
    # block an otherwise valid downgrade of the surrounding schema. The
    # correct "undo" is a re-ingestion (`uv run python scripts/backfill_sync.py
    # book`), which rebuilds book_genres from Open Library.
    pass
