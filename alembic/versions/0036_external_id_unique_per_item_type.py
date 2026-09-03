"""uq_external_id gains item_type — and the targets the old key lost are reopened

Issue #20.  ``uq_external_id`` was ``UNIQUE (source, external_id)``, with no
``item_type``.  TMDB numbers movies, series and people in **independent**
sequences that overlap, so id 110531 is legitimately both a series and an
actor — and whichever of the two got written first made the other permanently
unlinkable.  Worse, silently: both write paths (``upsert_external_id`` and
``_upsert_external_ids``) pre-check the pair and *skip* it, so the item row
lands in ``series``/``movies`` while the ``external_ids`` row never does, with
no exception, no counter and no log line.  Measured against the dev database
after enumerating the 752 series of 2022: 7 lost (0,93%), all 7 blocked by
``item_type='PERSON'`` rows, and the rate grows with ``people``, which fills
that same number space ~8-10x faster than the catalog does.

Two parts, in one transaction on purpose — the second is repair of damage
caused by the first, and must happen exactly once:

1. **DDL.**  ``uq_external_id`` becomes ``UNIQUE (item_type, source,
   external_id)``.  Same name on purpose: the constraint keeps its meaning
   ("one external id per item"), only its scope is corrected, and renaming it
   would invalidate every reference in the docs and the code comments for no
   gain.  Widening a unique key can never fail on existing data: anything that
   satisfied ``(source, external_id)`` satisfies the superset.

2. **DML.**  The items already lost have **no row to fix — they are missing a
   row**, and the external id cannot be recovered from ``external_ids``
   because it was never written there.  The one place that still remembers
   what the catalog wanted is ``seed_targets``, so the repair is to put the
   targets that were retired over this defect back on the work list
   (``attempts = 0``); the normal hydration then picks them up again and this
   time links them.  Only targets that are *unlinked* and *not* 404 at the
   source are touched, so nothing that legitimately converged is disturbed.

   The predicate is ``attempts > 0`` rather than
   ``attempts >= TMDB_SEED_MAX_ATTEMPTS``: that setting is a runtime env var,
   and a migration whose effect depends on the environment it happens to run
   in is not reproducible.  ``attempts > 0`` is a superset of "retired as
   unlinkable" for *any* value of it.  The extra rows it catches (targets that
   had burned 1..max-1 passes) were on the work list anyway; all they lose is
   accumulated partial burn.

   Re-hydrating an item that is already in the catalog does **not** duplicate
   it: ``bulk_load_items`` writes with ``ON CONFLICT ("slug") DO UPDATE`` and
   the per-item route upserts by slug too, so the existing row is updated and
   finally gets its ``external_ids`` link.

``uq_item_source`` (``item_type``, ``item_id``, ``source``) is untouched: it
already carried ``item_type`` and still says "one id per item per source".

Downgrade
---------
Re-tightening to the global ``UNIQUE (source, external_id)`` **can fail**, and
that is deliberate.  Once this migration has been live for a while the table
legitimately contains pairs shared across item types — exactly what it exists
to allow — and Postgres will refuse to build the narrower index with a
``duplicate key value violates unique constraint`` naming the offending pair.
There is no silent ``DELETE`` here to make that go away: dropping those rows
would delete real links with no way to tell which of the two claimants the old
code would have kept.  An operator who really needs to go back has to decide
which rows to sacrifice, and can list them with::

    SELECT source, external_id, array_agg(item_type ORDER BY item_type)
    FROM external_ids GROUP BY source, external_id HAVING COUNT(*) > 1;

The ``seed_targets`` repair is not undone.  ``attempts`` is a work counter,
not user data, and restoring the defect would have the hydration retire those
targets again by itself.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-04

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Reopen the targets the old key retired. See the module docstring for why this
# DML rides along with the DDL and why the predicate is ``attempts > 0``.
# Module-level so tests can exercise the predicate itself
# (tests/test_external_id_unique_per_type.py) instead of asserting it by eye.
REOPEN_UNLINKED_TARGETS_SQL = """
UPDATE seed_targets AS st
SET attempts = 0
WHERE st.attempts > 0
  AND st.unreachable_at IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM external_ids AS ei
      WHERE ei.item_type = st.item_type
        AND ei.source = st.source
        AND ei.external_id = st.external_id
  );
"""


def upgrade() -> None:
    op.drop_constraint("uq_external_id", "external_ids", type_="unique")
    op.create_unique_constraint(
        "uq_external_id", "external_ids", ["item_type", "source", "external_id"]
    )
    op.execute(REOPEN_UNLINKED_TARGETS_SQL)


def downgrade() -> None:
    op.drop_constraint("uq_external_id", "external_ids", type_="unique")
    # May raise on a catalog that has used the fix: see "Downgrade" above.
    op.create_unique_constraint("uq_external_id", "external_ids", ["source", "external_id"])
