"""search_expression_index — retire catalog_search, index the base tables

Feature 91, and the fix for issue #28.  Cross-type search lived in the
``catalog_search`` materialized view: a fifth copy of the catalog holding
``slug``/``title``/``overview``/``poster_url`` plus a stored ``tsvector``.
The problem was never its 137 MB by itself — it was that every ingestion had
to run ``REFRESH MATERIALIZED VIEW CONCURRENTLY``, and that builds a
**complete second copy** of the view before swapping it in.  With 127 MB free
of Neon's 512 MB, the refresh stopped fitting, and that is what blocked the
seeding.

After this migration ``movies``, ``series``, ``books`` and ``games`` each
carry their own ``search_vector`` as a ``GENERATED ALWAYS AS (...) STORED``
column with a GIN index, and the search query is a ``UNION ALL`` over the four
(``backlogg/search/repository.py``).  Postgres recomputes the vector inside
the statement that writes the row, transactionally, so **the refresh does not
get smaller — it stops existing**, and with it the window in which a freshly
ingested item was not yet searchable.

Why the column is stored and not just an expression index
---------------------------------------------------------

An expression index (``CREATE INDEX ... USING GIN (to_tsvector(...))``) would
have saved another ~57 MB, because the vector would live only inside the
index.  ``progress/measure_91.md`` measured, against production, whether that
was affordable and the answer was no: ``ts_rank`` is not decoration here.
Comparing the top-20 of seven real queries with and without it, **``ts_rank``
reorders between 35 % and 75 % of the page** — between 8 % and 44 % of the
matches have no ``rating_external`` at all, and all those NULLs tie with each
other, so in that band ``ts_rank`` is the *only* ordering criterion.  Keeping
it means the vector is read for every candidate row **before** the ``LIMIT``
(it sits in the ``ORDER BY``), and without a stored column that is a
recomputation of ``to_tsvector`` over half the corpus on a query like ``the``
(71.704 matches).  Hence: stored column, ~55 MB saved instead of ~112, and no
refresh either way.

Disk: what this costs while it runs, and the order that makes it fit
--------------------------------------------------------------------

Read this before deploying.  ``alembic/env.py`` wraps the whole upgrade in
**one** transaction, and that has a consequence that is easy to get backwards:

    ⚠️ ``DROP MATERIALIZED VIEW`` does **not** return those 137 MB to the
    filesystem when the statement runs.  Postgres unlinks the files at
    ``COMMIT``.  Dropping the view first *inside this migration* therefore
    buys exactly **zero** headroom for the ``ALTER``s that follow it.

Adding a ``STORED`` generated column rewrites the table: Postgres builds a new
heap and new copies of every index, and only unlinks the old ones at commit.
So while this migration runs the database holds, simultaneously:

=====================================================  ===============
Held at peak, on top of the starting size               Size
=====================================================  ===============
new heaps of the four content tables                    ~base + 57 MB
new copies of their existing indexes                    ~their size
the four new GIN indexes                                ~25 MB
the old heaps and indexes, until ``COMMIT``             (the base size)
the 137 MB of ``catalog_search``, until ``COMMIT``      137 MB
=====================================================  ===============

Measured, not assumed — on the dev database, 60.000 movie rows, a 25 MB
``catalog_search`` and a 62 MB database, watching ``pg_database_size`` from
inside the open transaction:

===================================  ==============  ==============
Moment                                DROP inside     DROP committed
                                      the ``BEGIN``   first
===================================  ==============  ==============
start                                 62 MB           62 MB
after the ``DROP``                    **62 MB**       36 MB
peak, mid-``ALTER``, before commit     **93 MB**      **67 MB**
after ``COMMIT``                      40 MB           40 MB
===================================  ==============  ==============

The second row is the whole point: inside the transaction the drop changes
nothing, and the peak ends up **26 MB higher — exactly the size of the view**.
Same end state either way; only the ceiling touched differs.

Scaled to production — 385 MB, a 137 MB view and four content tables at
roughly 90 MB of heap + indexes:

* **View dropped inside this migration** — peak ≈ 385 + 90 + 57 + 25 =
  **~557 MB**.  Over the 512 MB ceiling: the deploy fails.
* **View dropped and committed *before* the deploy** — the cluster starts at
  385 − 137 = 248 MB and the peak is ≈ 248 + 90 + 57 + 25 = **~420 MB**,
  about 90 MB of headroom.  This is the order that fits.

So the deploy sequence is, and the order is load-bearing:

1. ``psql "$DATABASE_URL" -c 'DROP MATERIALIZED VIEW catalog_search;'``
   — as its **own** committed statement, before the deploy.  ``/v1/search``
   returns 500 from this moment until step 2 finishes, because the code still
   on Render queries the view; on a free-tier instance that is a few minutes.
   This migration starts with ``DROP MATERIALIZED VIEW IF EXISTS`` precisely
   so that this manual step turns it into a no-op instead of a conflict.
2. Deploy ``main``.  Render runs this migration.
3. ``ANALYZE movies, series, books, games`` — the rewrite leaves fresh files
   (no ``VACUUM FULL`` needed, unlike feature 89) but no statistics for the
   new column, and the planner needs them to pick the GIN index.

If step 2 still does not fit, the ``ALTER``s can be applied by hand one table
at a time, each in its own transaction (smallest table first, so the cheapest
ones land even if the last one does not), followed by ``alembic stamp 0038``.
That lowers the peak to one table's rewrite instead of four.

The production column of that arithmetic is a **projection** from
``progress/measure_91.md``'s per-component breakdown: the per-table sizes have
not been measured against Neon (no production credentials in the session that
wrote this).  Measure before deploying, and note the ceiling is per
**cluster**, not per database:
``SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;``

Downgrade
---------

Fully reversible, and it has to be: it recreates ``catalog_search`` with the
same definition migration ``0031`` left behind — the same four sub-queries
including ``rating_internal``, the same ``search_vector`` expression — plus
its three indexes.  ``uq_catalog_search_type_id`` is not optional: without a
unique index ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` refuses to run (that
was feature 40 / migration ``0007``).  The downgrade needs the same headroom
in reverse: it rebuilds the 137 MB view *while* the four generated columns
still exist.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-07

"""

from collections.abc import Sequence

from alembic import op
from backlogg.shared.search_vector import SEARCH_VECTOR_SQL

# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The four content tables and the column each one calls its release date.
#: The view mapped them onto a single ``release_date`` output column and the
#: ``UNION ALL`` that replaced it has to reproduce that mapping exactly, or the
#: ``date_from``/``date_to`` filters silently stop working for series and
#: books.  Listed smallest-first is not meaningful here (all four are rewritten
#: in the same transaction); the order is the historical one of the view.
_CONTENT_TABLES: tuple[tuple[str, str], ...] = (
    ("movies", "release_date"),
    ("series", "first_air_date"),
    ("books", "first_publish_date"),
    ("games", "release_date"),
)


def _index_name(table: str) -> str:
    return f"idx_{table}_search_vector"


def upgrade() -> None:
    # First, and see the docstring for why this frees nothing until COMMIT:
    # ``IF EXISTS`` so the recommended pre-deploy manual drop makes this a
    # no-op rather than an error.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")

    for table, _date_column in _CONTENT_TABLES:
        # One shared constant, four identical expressions.  If these ever
        # drift, search starts behaving differently per content type with no
        # error and no failing test — see backlogg/shared/search_vector.py.
        # ``NOT NULL`` is free here (the rewrite already visits every row) and
        # it is *true*: ``title`` is NOT NULL on all four tables and
        # ``overview`` is COALESCEd, so ``to_tsvector`` can never return NULL.
        # Declared so the DB and the ORM models agree — otherwise a future
        # ``alembic revision --autogenerate`` would emit a phantom
        # ``alter_column(nullable=False)`` for four tables.
        op.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN search_vector tsvector "
            f"GENERATED ALWAYS AS ({SEARCH_VECTOR_SQL}) STORED "
            f"NOT NULL"
        )
        op.execute(f"CREATE INDEX {_index_name(table)} ON {table} USING GIN (search_vector)")


# ── downgrade ────────────────────────────────────────────────────────────────

# Verbatim from migration 0031, which is the definition production had before
# this feature: the four sub-queries, ``rating_internal`` included, and the
# per-type release-date column mapped onto a single output column.
_RECREATE_VIEW = f"""
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
    rating_internal,
    {SEARCH_VECTOR_SQL} AS search_vector
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
    rating_internal,
    {SEARCH_VECTOR_SQL}
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
    rating_internal,
    {SEARCH_VECTOR_SQL}
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
    rating_internal,
    {SEARCH_VECTOR_SQL}
FROM games
"""


def downgrade() -> None:
    for table, _date_column in _CONTENT_TABLES:
        # Dropping the column drops its GIN index with it, but naming the
        # index explicitly keeps the downgrade readable and independent of
        # that implicit behaviour.
        op.execute(f"DROP INDEX IF EXISTS {_index_name(table)}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP MATERIALIZED VIEW IF EXISTS catalog_search")
    op.execute(_RECREATE_VIEW)
    op.execute("CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector)")
    op.execute("CREATE INDEX idx_catalog_search_type ON catalog_search (item_type)")
    # Mandatory for REFRESH MATERIALIZED VIEW CONCURRENTLY (migration 0007).
    op.execute("CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id)")
