"""item_relations — the polymorphic edge table between catalog items

Feature 79 (wikidata_adaptations) creates the table described in
``docs/recommendations-plan.md`` («Capa 2 — Conocimiento»).  It is filled here
with Wikidata's explicit ``P144``/``P4969`` statements (novel -> film, film ->
game, comic -> series) and **feature 83 will fill the same table** with the
behavioural layer (item-item co-occurrence over user libraries,
``relation='COOCCURRENCE'``, ``source='INTERNAL'``).

No existing table is touched.  The Wikidata QID anchor of feature 79 needs no
schema change at all: it goes into ``external_ids`` with ``source='WIKIDATA'``,
a table that already allows several sources per item (``uq_item_source`` is
``(item_type, item_id, source)``).

Why the unique key carries ``source``
-------------------------------------

``uq_item_relation`` is ``(from_type, from_id, to_type, to_id, relation,
source)``.  Dropping ``source`` from it would make the knowledge layer and the
behaviour layer fight over the same row: a pair that is both a Wikidata
adaptation and a strong co-occurrence would have one of the two scores
silently overwritten by whichever job ran last, and the ranker could no longer
tell "two independent layers agree" from "one layer ran twice".  ``relation``
is in the key for the same reason on a smaller scale: ``P144`` and ``P4969``
are declared inverse properties in Wikidata, so a well-curated pair legitimately
produces both an ``ADAPTATION`` and a ``DERIVATIVE`` edge.

Because the two layers share the table, **no writer may issue a wide DELETE**.
The rule and its single safe implementation live in
``backlogg/shared/item_relations.py`` (``delete_relations_by_source``).

Indexes
-------

Only one secondary index, on the ``to`` side.  The forward read — "given this
item, what does it point at" — is already covered by the leading columns of
``uq_item_relation``'s index, so a second index on ``(from_type, from_id)``
would duplicate it and be paid for on every write of a table that feature 83
will grow by orders of magnitude.  The reverse read has no such cover and is
not optional: direction here encodes *which end adapts which*, not relevance,
so the page of the novel must be able to find the film that points at it.

``score`` exists from the start even though Wikidata always writes ``1.0``.
An explicit ``P144`` statement is an assertion, not an estimate — but feature
83 writes a real cosine, and adding the column later would mean migrating a
table that by then has rows in it.

``ck_item_relation_not_self`` rejects an item related to itself: a handful of
Wikidata entities point at their own QID, and the effect downstream would be
recommending the page the user is already on.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_relations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("from_type", sa.String(length=20), nullable=False),
        sa.Column("from_id", sa.BigInteger(), nullable=False),
        sa.Column("to_type", sa.String(length=20), nullable=False),
        sa.Column("to_id", sa.BigInteger(), nullable=False),
        # ADAPTATION | DERIVATIVE (feature 79) | COOCCURRENCE (feature 83)
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        # WIKIDATA (feature 79) | INTERNAL (feature 83)
        sa.Column("source", sa.String(length=20), nullable=False),
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
        sa.UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "relation",
            "source",
            name="uq_item_relation",
        ),
        sa.CheckConstraint(
            "NOT (from_type = to_type AND from_id = to_id)",
            name="ck_item_relation_not_self",
        ),
    )
    op.create_index(
        "idx_item_relations_to",
        "item_relations",
        ["to_type", "to_id", "relation"],
    )
    # Reuses trigger_set_updated_at() defined in 0001, same as seed_targets
    # (0035) and sync_watermarks (0039).
    op.execute(
        """
        CREATE TRIGGER set_updated_at_item_relations
        BEFORE UPDATE ON item_relations
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_item_relations ON item_relations;")
    op.drop_index("idx_item_relations_to", table_name="item_relations")
    op.drop_table("item_relations")
