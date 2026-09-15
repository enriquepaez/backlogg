"""item_embeddings — pgvector + one halfvec per catalog item (feature 75)

Creates the *Capa 1 — Semántica* of ``docs/recommendations-plan.md``: the
``vector`` extension, a polymorphic ``item_embeddings`` table and the HNSW
index that makes cross-type nearest-neighbour reads a single lookup.

No existing table is touched.  The vector lives in its own table rather than as
a column on ``movies``/``series``/``books``/``games`` for the same reason
``external_ids`` and ``item_relations`` do: four columns would mean four HNSW
indexes and a four-way UNION for every cross-type read, which is precisely the
operation this layer exists to make free.

``halfvec``, and the dimension comes from the environment
---------------------------------------------------------

``halfvec(EMBEDDING_DIM)``, not ``vector``: two bytes per component instead of
four, halving table **and** index, for a quantisation error far under the noise
floor of a sentence embedding.  Disk is the binding constraint here — Neon free
is 512 MB per project and the full catalog is projected at 444-488 MB (issue
#28) — so this is not a micro-optimisation, it is what makes the layer fit at
all.

The dimension is read from ``settings.EMBEDDING_DIM`` (384, the native width of
``intfloat/multilingual-e5-small``) because the acceptance list requires it to
be configurable.  The consequence is worth stating plainly: the value is
**baked into the column type** at migration time.  Changing the variable
afterwards does not migrate anything — every write then fails with ``expected
384 dimensions``.  ``get_embedding_column_dim`` in
``backlogg/shared/item_embeddings.py`` turns that into a readable error, and
``docs/operations.md`` documents the ``ALTER TABLE`` needed to actually change
it.

Why HNSW and why cosine
-----------------------

HNSW over IVFFlat: IVFFlat needs a representative sample to build its lists, so
it cannot be created on the empty table this migration leaves behind — it would
have to be a second, manual step after the first generation, and a forgotten
one is a sequential scan nobody notices.  HNSW builds incrementally and is
correct from row zero.

``halfvec_cosine_ops`` because the embeddings are compared by angle, not
magnitude; the model is trained for cosine.  Alembic cannot express an operator
class in ``create_index``, hence the raw ``CREATE INDEX``.

There is no ``(item_type)`` index: filtering by type is a *narrowing* of an ANN
query that is already ordered by distance, and a b-tree on a four-value column
would be ignored anyway.  ``uq_item_embedding`` covers the only other read —
"does this item have a vector".

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from backlogg.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# pgvector caps halfvec storage at 16.000 dimensions and halfvec *indexing* at
# 4.000.  An out-of-range value would fail halfway through the migration with a
# Postgres error about the type; failing here says which knob is wrong.
_MAX_INDEXABLE_DIM = 4000


class _HalfVec(sa.types.UserDefinedType):
    """Just enough of ``halfvec(n)`` to emit the DDL.

    Declared inline instead of importing ``backlogg.shared.item_embeddings``:
    a migration has to keep producing the same DDL years after the application
    type it mirrors has been renamed, moved or deleted.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"halfvec({self.dim})"


def _dim() -> int:
    dim = settings.EMBEDDING_DIM
    if not 1 <= dim <= _MAX_INDEXABLE_DIM:
        raise ValueError(
            f"EMBEDDING_DIM={dim} is outside 1..{_MAX_INDEXABLE_DIM} — pgvector cannot "
            f"build an HNSW index on a halfvec wider than {_MAX_INDEXABLE_DIM}"
        )
    return dim


def upgrade() -> None:
    # Neon supports this on every plan, free included, with no add-on
    # (verified 2026-09-15). Locally it needs the pgvector/pgvector:pg16 image:
    # the official postgres:16 does not even list `vector` in
    # pg_available_extensions. See docs/operations.md.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    dim = _dim()
    op.create_table(
        "item_embeddings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # MOVIE | SERIES | BOOK | GAME — polymorphic, no FK, like external_ids
        # and item_relations. Integrity is the application's job.
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", _HalfVec(dim), nullable=False),
        # Which model produced the vector: a different model means a different
        # space, so the row has to be redone even if the text is identical.
        sa.Column("model", sa.String(length=120), nullable=False),
        # SHA-256 of the exact serialised source text. This column is what lets
        # the monthly job skip an item whose title, genres and synopsis have not
        # changed — without it every run would re-embed the whole subset.
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_id", name="uq_item_embedding"),
    )
    op.execute(
        "CREATE INDEX idx_item_embeddings_hnsw ON item_embeddings "
        "USING hnsw (embedding halfvec_cosine_ops)"
    )
    # Reuses trigger_set_updated_at() defined in 0001, same as item_relations
    # (0041), seed_targets (0035) and sync_watermarks (0039).
    op.execute(
        """
        CREATE TRIGGER set_updated_at_item_embeddings
        BEFORE UPDATE ON item_embeddings
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_item_embeddings ON item_embeddings;")
    op.execute("DROP INDEX IF EXISTS idx_item_embeddings_hnsw")
    op.drop_table("item_embeddings")
    # Dropping the extension is safe precisely because nothing else in the
    # schema uses it: `item_embeddings` is the only vector-typed object, and a
    # later migration that added another would be downgraded before this one.
    # It is dropped rather than left behind so upgrade/downgrade really are
    # inverses — the re-upgrade recreates it with IF NOT EXISTS.
    op.execute("DROP EXTENSION IF EXISTS vector")
