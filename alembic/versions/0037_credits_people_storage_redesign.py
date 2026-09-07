"""credits_people_storage_redesign — split the detail-page cast from the graph

Feature 89.  Production ran out of Neon's 512 MB with the catalog two thirds
seeded (series at **zero**), and the measurement (``progress/measure_89.md``)
said why: ``credits`` (136 MB) + ``people`` (56 MB) + ``external_ids`` (74 MB)
were **55 % of the whole database** for 85.530 items, and 46,9 % of ``people``
were actors appearing exactly once in the entire catalog.

This migration does the two things that measurement justified:

**A — narrow ``credits``.**  ``item_type`` stops being ``VARCHAR(20)`` and
``role`` stops being ``VARCHAR(50)``: both become ``smallint`` (the mapping is
``backlogg/shared/codes.py``, which also explains why not a native ENUM).  The
surrogate ``id`` disappears — nothing ever referenced it and ``uq_credit`` was
already the identity — and the natural key becomes the primary key.  That key
is reordered to ``(item_id, person_id, item_type, role)``: leading with a
``smallint`` followed by two ``bigint``s forces 6 bytes of alignment padding
per row, ~7 MB in the table and again in the key, for nothing.

**B — the cast leaves the relational model.**  ``item_cast`` holds one JSONB
array per item, ordered by billing order and never truncated; ``credits`` and
``people`` keep only the roles that build the navigation graph (``DIRECTOR``,
``CREATOR``, ``WRITER``, ``AUTHOR``, ``SOURCE_AUTHOR``).  People who were
*only* cast lose their ``people`` and ``external_ids`` rows; people who direct
or write **and** also act keep everything except their ``ACTOR`` credits.

Rebuilt, not altered
--------------------

``credits`` is recreated and swapped rather than ``ALTER``ed column by column.
Three reasons: ``ALTER COLUMN TYPE`` rewrites the table anyway; dropping
columns does **not** reclaim their space or reorder the physical layout, so
the alignment win above would not materialise without a ``VACUUM FULL`` this
migration cannot run inside its transaction; and only 27 % of the rows survive
the filter, so copying them is cheaper than rewriting all 710.772.

Batching, and why it still cannot leave things half done
--------------------------------------------------------

Render applies this on deploy against 710.772 rows, so every bulk step walks
``item_id`` in windows of ``_WINDOW`` instead of issuing one statement over
the whole table — bounded work and bounded memory per statement.  The windows
are **not** separate transactions: ``alembic/env.py`` wraps the whole run in
one, which is what makes "no half-migrated database" true.  A failure in
window 40 rolls back windows 1-39 with it.

Disk headroom this needs — read before deploying
-------------------------------------------------

Everything here runs in **one** transaction, so nothing is returned to the
filesystem until it commits.  While it runs, the database holds *everything at
once* — the old objects and the new ones:

============================================  ==========
Held simultaneously, on top of the old table   Size
============================================  ==========
``item_cast`` (table + primary key)            ~34 MB
new ``credits`` table + its primary key        ~25-30 MB
its three secondary indexes                    ~12-15 MB
``_f89_cast_only_people`` + its index          ~10 MB
dead tuples and WAL of the two ``DELETE``s     several MB
============================================  ==========

That is a **peak of ~80-90 MB above the starting size**, not the ~60-70 MB an
earlier draft of this docstring claimed: the secondary indexes are built before
the commit, and the temp table stays alive through the whole expensive stretch.
Production started this feature at 484 MB of Neon's 512 MB ceiling — about 28 MB
of headroom — so **the migration does not fit as-is and the deploy has to make
room first**.  Measured on the dev database, before/after/after a
``VACUUM FULL``:

===============  ========  ==========  ===================
Table            Before    After       After VACUUM FULL
===============  ========  ==========  ===================
``credits``      3.616 kB  488 kB      488 kB
``people``       3.472 kB  3.472 kB    624 kB
``external_ids`` 3.552 kB  3.552 kB    1.048 kB
``item_cast``    —         1.080 kB    1.080 kB
**total**        10.640 kB 8.592 kB    3.240 kB
===============  ========  ==========  ===================

Two operational consequences, neither of which a migration can do for itself:

1. **Make room before applying it.**  ``catalog_search`` (105 MB, a
   materialized view of derived data) is the cheapest lever: drop it, deploy,
   recreate and ``REFRESH`` it.
2. **``VACUUM FULL people`` and ``VACUUM FULL external_ids`` afterwards.**
   ``DELETE`` marks tuples dead; it does not shrink the file.  ``credits`` does
   not need it (it is recreated, so its file is new), but without those two the
   ~80 MB this feature frees in ``people``/``external_ids`` stays on disk as
   reusable-but-not-returned space.  ``VACUUM FULL`` cannot run inside a
   transaction, so it cannot live here.

Downgrade: what comes back and what does not
--------------------------------------------

The schema comes back in full and so do the graph credits, exactly.  The cast
does **not**, and cannot:

* **Recovered** — an ``ACTOR`` credit is rebuilt from ``item_cast`` for every
  payload entry whose name still matches a surviving ``people`` row, with its
  character and billing order.  In production that is the ~9.251 people who
  direct/write *and* act (60.095 credits): the Clint Eastwood case.
* **Not recovered** — the 175.306 cast-only people.  Their ``people`` rows and
  their ``external_ids`` rows were deleted, and ``item_cast`` stores a name,
  not an identity: there is no TMDB id in the payload to re-link them by, and
  inventing ``people`` rows from names would fabricate slugs, external ids and
  identities that never existed.  Their credits therefore do not come back
  either.  ``created_at`` is lost for every rebuilt row (defaults to now).

The way back is re-ingestion, not the downgrade: ``scripts/backfill_sync.py
<type> --only-missing-credits --recheck`` refetches cast and crew from TMDB
and repopulates all three tables.  The downgrade is a schema rollback with a
best-effort data rollback, and this docstring is the honest label on it.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from backlogg.shared.codes import CREDIT_ROLE_CODES, ITEM_TYPE_CODES

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Rows of ``credits`` walked per statement.  Windows are over ``item_id``, so
#: this is a *span* of ids and not a row count: with ~8 credits per item and
#: item ids in the tens of thousands, 20.000 covers a few tens of thousands of
#: rows per statement — small enough to bound memory, large enough that a
#: 710k-row table takes a handful of statements rather than hundreds.
_WINDOW = 20_000

#: The role rows of ``credits`` keep.  ``ACTOR`` is the complement and is the
#: one that moves to ``item_cast``; see ``backlogg.shared.credits``.
_CAST_ROLE = "ACTOR"

#: Only these four ever appear in ``credits``.  ``PERSON`` is an
#: ``external_ids`` type, never an item a credit points at.
_CREDIT_ITEM_TYPES = ("MOVIE", "SERIES", "BOOK", "GAME")


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _case_to_code(column: str, codes: dict[str, int]) -> str:
    """``CASE <column> WHEN 'MOVIE' THEN 1 ... END`` — no ``ELSE`` on purpose.

    An unlisted value yields NULL and the NOT NULL column rejects it, so a
    vocabulary this migration does not know about aborts the run instead of
    being silently dropped.  ``_assert_known_vocabulary`` gets there first with
    a readable message; this is the belt to that pair of braces.
    """
    whens = " ".join(f"WHEN '{name}' THEN {code}" for name, code in codes.items())
    return f"CASE {column} {whens} END"


def _case_to_name(column: str, codes: dict[str, int]) -> str:
    whens = " ".join(f"WHEN {code} THEN '{name}'" for name, code in codes.items())
    return f"CASE {column} {whens} END"


def _assert_known_vocabulary(bind: sa.Connection) -> None:
    """Fail loudly, and before writing anything, on an unmappable value.

    Silently dropping credits whose ``item_type`` or ``role`` is not in the
    vocabulary would lose catalog data in a migration whose whole purpose is
    to make the catalog fit; aborting costs a deploy and loses nothing.

    ``item_type`` is checked against ``_CREDIT_ITEM_TYPES``, **not** against
    the whole of ``ITEM_TYPE_CODES``.  The difference is ``PERSON``, which is
    an ``external_ids`` type and never something a credit points at: a row
    with ``item_type = 'PERSON'`` would pass a check against the full
    vocabulary and then land in *neither* table — ``_BACKFILL_ITEM_CAST``
    filters it out and ``_COPY_GRAPH_CREDITS`` only takes the non-cast roles.
    Measured against production it is zero rows today (only ``MOVIE`` and
    ``BOOK`` exist), so this closes a hole rather than plugging a leak — but
    it is a one-line hole of exactly the shape that produced issues #7, #15
    and #20, and this migration cannot be re-run to recover what it drops.
    """
    for column, vocabulary in (
        ("item_type", _CREDIT_ITEM_TYPES),
        ("role", tuple(CREDIT_ROLE_CODES)),
    ):
        unknown = (
            bind.execute(
                sa.text(
                    f"SELECT DISTINCT {column} FROM credits "
                    f"WHERE {column} NOT IN ({_sql_list(vocabulary)})"
                )
            )
            .scalars()
            .all()
        )
        if unknown:
            raise RuntimeError(
                f"credits.{column} holds values this migration cannot map: "
                f"{sorted(unknown)!r}. Every row has to end up in either "
                f"credits or item_cast, and these would end up in neither. "
                f"Add them to backlogg/shared/codes.py (codes are "
                f"append-only), extend the vocabulary checked here, and "
                f"re-run the migration."
            )


def _walk_windows(bind: sa.Connection, statement: str, source: str, column: str) -> None:
    """Run ``statement`` once per ``_WINDOW``-wide slice of ``source.column``.

    ``statement`` must take ``:lo`` and ``:hi``.  Empty source -> no work.
    """
    bounds = bind.execute(sa.text(f"SELECT MIN({column}), MAX({column}) FROM {source}")).one()
    low, high = bounds
    if low is None:
        return
    lo = int(low)
    while lo <= int(high):
        bind.execute(sa.text(statement), {"lo": lo, "hi": lo + _WINDOW})
        lo += _WINDOW


# ── upgrade ──────────────────────────────────────────────────────────────────

# One row per item, cast ordered by billing order with the unknown ones last.
# ``jsonb_strip_nulls`` is what makes ``c``/``o`` optional keys, matching
# ``backlogg.shared.credits.build_cast_payload``; ``NULLIF`` makes an empty
# character name behave like a missing one, as that function does.
#
# ``p.name <> ''`` is the **one thing this migration drops on purpose**, and it
# is written here because a silent discard inside a data migration should never
# have to be inferred from the SQL.  A nameless cast entry would render as a
# blank line on the detail page and carries nothing else — no character, no
# identity — so ``build_cast_payload`` drops it on ingestion too, and this
# clause is what keeps the backfill agreeing with the live write path.  It is
# **zero rows in production** (verified: no ``people`` row reachable from an
# ACTOR credit has an empty name), so nothing is actually lost today; the
# clause exists so that if one ever appears it behaves the same on both paths.
_BACKFILL_ITEM_CAST = f"""
INSERT INTO item_cast (item_type, item_id, payload)
SELECT
    {_case_to_code("c.item_type", ITEM_TYPE_CODES)},
    c.item_id,
    jsonb_agg(
        jsonb_strip_nulls(jsonb_build_object(
            'n', p.name,
            'c', NULLIF(c.character_name, ''),
            'o', c.billing_order
        ))
        ORDER BY c.billing_order ASC NULLS LAST, p.name ASC
    )
FROM credits AS c
JOIN people AS p ON p.id = c.person_id
WHERE c.role = '{_CAST_ROLE}'
  AND c.item_type IN ({_sql_list(_CREDIT_ITEM_TYPES)})
  AND p.name <> ''
  AND c.item_id >= :lo AND c.item_id < :hi
GROUP BY c.item_type, c.item_id
ON CONFLICT (item_type, item_id) DO UPDATE SET payload = EXCLUDED.payload
"""

_COPY_GRAPH_CREDITS = f"""
INSERT INTO credits_new (item_id, person_id, item_type, role, created_at)
SELECT
    c.item_id,
    c.person_id,
    {_case_to_code("c.item_type", ITEM_TYPE_CODES)},
    {_case_to_code("c.role", CREDIT_ROLE_CODES)},
    c.created_at
FROM credits AS c
WHERE c.role <> '{_CAST_ROLE}'
  AND c.item_id >= :lo AND c.item_id < :hi
ON CONFLICT DO NOTHING
"""

# People whose *only* reason to exist was the cast.  Computed from the old
# table, before it is dropped; the deletes themselves happen after the swap so
# the ``ON DELETE CASCADE`` they trigger walks the new (graph-only) table.
_COLLECT_CAST_ONLY_PEOPLE = f"""
CREATE TEMP TABLE _f89_cast_only_people ON COMMIT DROP AS
SELECT DISTINCT c.person_id AS id
FROM credits AS c
WHERE c.role = '{_CAST_ROLE}'
  AND NOT EXISTS (
      SELECT 1 FROM credits AS other
      WHERE other.person_id = c.person_id AND other.role <> '{_CAST_ROLE}'
  )
"""


def upgrade() -> None:
    bind = op.get_bind()
    _assert_known_vocabulary(bind)

    # ── item_cast ────────────────────────────────────────────────────────────
    op.create_table(
        "item_cast",
        sa.Column("item_type", sa.SmallInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("item_type", "item_id"),
    )
    _walk_windows(bind, _BACKFILL_ITEM_CAST, "credits", "item_id")

    # ── who is about to lose their people row ────────────────────────────────
    bind.execute(sa.text(_COLLECT_CAST_ONLY_PEOPLE))
    bind.execute(sa.text("CREATE INDEX ON _f89_cast_only_people (id)"))

    # ── the narrow credits ───────────────────────────────────────────────────
    # Column order is deliberate: the two bigints first, so the two smallints
    # pack into the tail instead of forcing 6 bytes of alignment padding.
    op.create_table(
        "credits_new",
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.SmallInteger(), nullable=False),
        sa.Column("role", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "person_id", "item_type", "role"),
    )
    _walk_windows(bind, _COPY_GRAPH_CREDITS, "credits", "item_id")

    op.drop_table("credits")
    op.rename_table("credits_new", "credits")
    op.execute("ALTER TABLE credits RENAME CONSTRAINT credits_new_pkey TO credits_pkey")
    op.execute(
        "ALTER TABLE credits RENAME CONSTRAINT credits_new_person_id_fkey TO credits_person_id_fkey"
    )
    op.create_index("idx_credits_person", "credits", ["person_id"])
    op.create_index("idx_credits_item", "credits", ["item_type", "item_id"])
    op.create_index("idx_credits_role", "credits", ["role"])

    # ── purge the people who were only ever cast ─────────────────────────────
    _walk_windows(
        bind,
        "DELETE FROM external_ids WHERE item_type = 'PERSON' AND item_id IN "
        "(SELECT id FROM _f89_cast_only_people WHERE id >= :lo AND id < :hi)",
        "_f89_cast_only_people",
        "id",
    )
    _walk_windows(
        bind,
        "DELETE FROM people WHERE id IN "
        "(SELECT id FROM _f89_cast_only_people WHERE id >= :lo AND id < :hi)",
        "_f89_cast_only_people",
        "id",
    )
    op.execute("DROP TABLE _f89_cast_only_people")


# ── downgrade ────────────────────────────────────────────────────────────────

_RESTORE_GRAPH_CREDITS = f"""
INSERT INTO credits_old (item_type, item_id, person_id, role, created_at)
SELECT
    {_case_to_name("c.item_type", ITEM_TYPE_CODES)},
    c.item_id,
    c.person_id,
    {_case_to_name("c.role", CREDIT_ROLE_CODES)},
    c.created_at
FROM credits AS c
WHERE c.item_id >= :lo AND c.item_id < :hi
ON CONFLICT ON CONSTRAINT uq_credit DO NOTHING
"""

# Best effort, and only for people who still exist: see "Downgrade" above.
# The name -> id map is materialised because ``people`` has no btree index on
# ``name`` (only a GIN over its tsvector), and one sequential scan per cast
# entry would make this unrunnable on a real catalog.
_RESTORE_CAST_CREDITS = f"""
INSERT INTO credits_old (item_type, item_id, person_id, role, character_name, billing_order)
SELECT
    {_case_to_name("ic.item_type", ITEM_TYPE_CODES)},
    ic.item_id,
    known.id,
    '{_CAST_ROLE}',
    entry.value ->> 'c',
    (entry.value ->> 'o')::int
FROM item_cast AS ic
CROSS JOIN LATERAL jsonb_array_elements(ic.payload) AS entry(value)
JOIN _f89_person_by_name AS known ON known.name = entry.value ->> 'n'
WHERE ic.item_id >= :lo AND ic.item_id < :hi
ON CONFLICT ON CONSTRAINT uq_credit DO NOTHING
"""


def downgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "credits_old",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("character_name", sa.String(length=255), nullable=True),
        sa.Column("billing_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_id", "person_id", "role", name="uq_credit"),
    )
    _walk_windows(bind, _RESTORE_GRAPH_CREDITS, "credits", "item_id")

    bind.execute(
        sa.text(
            "CREATE TEMP TABLE _f89_person_by_name ON COMMIT DROP AS "
            "SELECT DISTINCT ON (name) name, id FROM people ORDER BY name, id"
        )
    )
    bind.execute(sa.text("CREATE INDEX ON _f89_person_by_name (name)"))
    _walk_windows(bind, _RESTORE_CAST_CREDITS, "item_cast", "item_id")
    op.execute("DROP TABLE _f89_person_by_name")

    op.drop_table("credits")
    op.rename_table("credits_old", "credits")
    op.execute("ALTER TABLE credits RENAME CONSTRAINT credits_old_pkey TO credits_pkey")
    op.execute(
        "ALTER TABLE credits RENAME CONSTRAINT credits_old_person_id_fkey TO credits_person_id_fkey"
    )
    op.execute("ALTER SEQUENCE credits_old_id_seq RENAME TO credits_id_seq")
    op.create_index("idx_credits_person", "credits", ["person_id"])
    op.create_index("idx_credits_item", "credits", ["item_type", "item_id"])
    op.create_index("idx_credits_role", "credits", ["role"])

    op.drop_table("item_cast")
