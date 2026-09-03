"""Issue #20 — ``uq_external_id`` is unique per item type, and the repair of it.

The constraint itself and both write paths are covered in
``tests/shared/test_models.py`` and ``tests/shared/test_bulk_load.py``. What is
left here is the part of migration ``0036`` that no schema assertion reaches:
the ``UPDATE`` that puts the ``seed_targets`` retired over this defect back on
the work list.

Why it needs a test of its own: the items that were lost have **no row to
correct — they are missing a row**, so the only evidence that the catalog ever
wanted them is ``seed_targets``. If that predicate is wrong the repair either
does nothing (the catalog keeps its hole) or reopens targets that are legally
retired (the nightly slice burns passes on 404s forever). The SQL is imported
from the migration module rather than retyped, so the two cannot drift.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from backlogg.scheduler.repository import (
    SeedTargetRow,
    count_seed_target_progress,
    get_pending_seed_targets,
    upsert_seed_targets,
)
from backlogg.series.models import Series
from backlogg.shared.external_ids import upsert_external_id

# ``alembic/versions`` is not an importable package, so the revision is loaded
# by path — the same trick ``tests/test_tmdb_discover_seeding.py`` uses for
# ``scripts/``.
_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "0036_external_id_unique_per_item_type.py"
)
_spec = importlib.util.spec_from_file_location("migration_0036", _MIGRATION_PATH)
migration_0036 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0036)


async def _attempts(db, external_id: str) -> int:
    row = (
        await db.execute(
            text("SELECT attempts FROM seed_targets WHERE external_id = :e"),
            {"e": external_id},
        )
    ).one()
    return row.attempts


async def test_migration_reopens_only_the_targets_the_old_key_lost(db):
    """The repair predicate, row by row.

    Four targets, one per case the ``UPDATE`` has to tell apart:

    * ``880001`` — burned its passes and never linked: **reopened**. This is
      the lost item, the one whose row is in ``series`` without its link.
    * ``880002`` — burned passes but *is* linked: untouched, it converged (its
      ``attempts`` are history, not a pending debt).
    * ``880003`` — unlinked but 404 at TMDB: untouched. That answer does not
      change with the constraint, and reopening it would spend a slice slot on
      every run forever.
    * ``880004`` — never attempted: untouched, it was already workable.
    """
    now = datetime.now(UTC)
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("SERIES", "TMDB", "880001", vote_count=900, release_year=2022),
            SeedTargetRow("SERIES", "TMDB", "880002", vote_count=800, release_year=2022),
            SeedTargetRow("SERIES", "TMDB", "880003", vote_count=700, release_year=2022),
            SeedTargetRow("SERIES", "TMDB", "880004", vote_count=600, release_year=2022),
        ],
    )
    linked = Series(
        title="Repair Linked Series",
        slug="repair-linked-series-20",
        last_synced_at=now,
    )
    db.add(linked)
    await db.flush()
    await upsert_external_id(db, "SERIES", linked.id, "TMDB", "880002")
    await db.execute(
        text(
            "UPDATE seed_targets SET attempts = 3 "
            "WHERE source = 'TMDB' AND external_id IN ('880001', '880002')"
        )
    )
    await db.execute(
        text(
            "UPDATE seed_targets SET attempts = 1, unreachable_at = :now "
            "WHERE source = 'TMDB' AND external_id = '880003'"
        ),
        {"now": now},
    )
    await db.flush()

    assert await get_pending_seed_targets(db, "SERIES", "TMDB", 10, 3) == ["880004"]

    await db.execute(text(migration_0036.REOPEN_UNLINKED_TARGETS_SQL))
    await db.flush()

    assert await _attempts(db, "880001") == 0
    assert await _attempts(db, "880002") == 3
    assert await _attempts(db, "880003") == 1
    assert await _attempts(db, "880004") == 0

    # And the reopened one is genuinely back on the work list, ahead of nothing
    # it should not be ahead of (the order is attempts, then vote_count).
    assert await get_pending_seed_targets(db, "SERIES", "TMDB", 10, 3) == ["880001", "880004"]
    progress = await count_seed_target_progress(db, "SERIES", "TMDB", 3)
    assert progress.pending == 2
    assert progress.gone == 1
    assert progress.unlinkable == 0


async def test_migration_repair_is_idempotent(db):
    """Running it twice changes nothing the second time.

    It lives inside a migration precisely so it runs exactly once, but a
    re-run must not be destructive either — an operator replaying the SQL by
    hand after a partial deploy should not be able to make things worse.
    """
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "881001", vote_count=500, release_year=2019)]
    )
    await db.execute(
        text(
            "UPDATE seed_targets SET attempts = 5 WHERE source = 'TMDB' AND external_id = '881001'"
        )
    )
    await db.flush()

    await db.execute(text(migration_0036.REOPEN_UNLINKED_TARGETS_SQL))
    await db.flush()
    first = await _attempts(db, "881001")

    await db.execute(text(migration_0036.REOPEN_UNLINKED_TARGETS_SQL))
    await db.flush()
    assert await _attempts(db, "881001") == first == 0
