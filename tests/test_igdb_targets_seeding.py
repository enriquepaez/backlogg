"""Tests for feature 90 — igdb_targets_seeding.

Games were the last content type seeded by a cursor.  This file covers the
conversion, matching the feature's acceptance list:

1. **The IGDB enumeration query** — the quality filter (``game_type``
   allowlist plus ``rating > 0``) travels in the ``where``, the walk is keyset
   (``id > N`` + ``sort id asc``) and never uses ``offset``.
2. **The enumeration produces targets** — a page of IGDB rows becomes
   ``seed_targets`` rows, with ``rating_count`` as the notoriety order and the
   release year parsed out of IGDB's epoch seconds.
3. **A game that fails the filter never enters** — it is excluded at the
   source by the ``where``, and a row with no usable id is dropped by the
   mapper rather than written as a target.
4. **An already linked target is not re-enumerated into work** — a game the
   catalog holds is out of the pending difference, and re-running the
   enumeration over it keeps its counters instead of resetting them.
5. **The hydration is target-driven** — ``sync_games`` consumes
   ``seed_targets`` by difference against ``external_ids``, tops the slice up
   with the ``last_synced_at`` rotation, retires ids IGDB no longer serves,
   and its ``pending``/``stuck`` counters work exactly as they do for movies.
6. **The cursor is gone** — ``sync_games`` neither reads nor writes
   ``sync_cursors``, and ``SEED_TOP_N_GAMES`` no longer exists at all.

The database-backed tests run against the real test database; IGDB is always
mocked, so no test touches the network.
"""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from backlogg.core.config import settings
from backlogg.games.adapters.igdb import IGDB_PAGE_SIZE, IGDBClient
from backlogg.games.constants import (
    ALLOWED_GAME_CATEGORY_IDS,
    ALLOWED_GAME_TYPES,
    GAME_TYPE_MAP,
)
from backlogg.games.models import Game
from backlogg.scheduler import igdb_catalog
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import (
    SEED_TARGET_SOURCES,
    SeedTargetRow,
    count_seed_target_progress,
    get_pending_seed_targets,
    mark_seed_targets_attempted,
    mark_seed_targets_unreachable,
    upsert_seed_targets,
)
from backlogg.shared.external_ids import upsert_external_id

# Mirrors the production default; the retirement tests set it explicitly.
_MAX_ATTEMPTS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mocked_session_factory(session):
    """Session factory whose context manager yields ``session``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _igdb_game(igdb_id: int, name: str, **overrides) -> dict:
    """A raw IGDB detail payload, the shape ``game_to_dict`` consumes."""
    raw = {
        "id": igdb_id,
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "game_type": 0,
        "rating": 82.0,
        "rating_count": 400,
        "first_release_date": 1_262_304_000,  # 2010-01-01
    }
    raw.update(overrides)
    return raw


def _catalog_row(igdb_id: int, rating_count: int | None = 100, stamp: int | None = None) -> dict:
    """A row of the *enumeration* query: three fields, no detail."""
    return {
        "id": igdb_id,
        "rating_count": rating_count,
        "first_release_date": stamp,
    }


def _game(slug: str, *, synced_days_ago: int = 0) -> Game:
    return Game(
        title=slug.replace("-", " ").title(),
        slug=slug,
        game_type="MAIN_GAME",
        last_synced_at=datetime.now(UTC) - timedelta(days=synced_days_ago),
    )


# ── 1. The enumeration query ──────────────────────────────────────────────────


async def test_catalog_page_query_is_keyset_and_carries_the_quality_filter():
    """``where <filter> & id > N; sort id asc`` — and no ``offset`` anywhere.

    Offset is not merely unused, it must be *absent*: it works against IGDB
    (unlike TMDB there is no page cap) but it walks a set that moves, since
    ``rating > 0`` changes with no publication event at all.
    """
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_catalog_page(after=100000, limit=500)

    mock_post.assert_awaited_once()
    endpoint, body = mock_post.call_args.args
    assert endpoint == "games"
    assert " id > 100000;" in body
    assert " sort id asc;" in body
    assert " limit 500;" in body
    assert "offset" not in body
    # The filter of feature 65, whole: allowlist + a rating.
    assert f"game_type = ({','.join(str(i) for i in sorted(ALLOWED_GAME_CATEGORY_IDS))})" in body
    assert "rating > 0" in body
    # Enumeration payload: three fields, not the twenty of a detail request.
    assert body.startswith("fields id,rating_count,first_release_date;")


async def test_catalog_page_never_asks_for_more_than_igdb_serves():
    """IGDB caps a response at 500 no matter what ``limit`` says."""
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_catalog_page(after=0, limit=5000)

    assert f" limit {IGDB_PAGE_SIZE};" in mock_post.call_args.args[1]


async def test_hydration_asks_for_a_batch_of_ids_in_one_request():
    """``where id = (...)`` — 500 fully hydrated games per request, not 500 requests.

    This is what makes converting games to ``seed_targets`` cheap where TMDB's
    conversion was not: TMDB has no bulk detail endpoint.
    """
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_games_by_ids(["11", "22", "33"])

    body = mock_post.call_args.args[1]
    assert " where id = (11,22,33);" in body
    assert " limit 3;" in body
    # No quality clause: the ids come from the work list, and a game that lost
    # its rating must still be refreshable instead of looking like a 404.
    assert "rating > 0" not in body
    assert "game_type" in body  # ...as a requested *field*, not as a filter
    assert "where game_type" not in body


async def test_hydration_of_an_empty_id_list_touches_no_network():
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
        assert await client.get_games_by_ids([]) == []
    mock_post.assert_not_awaited()


async def test_hydration_refuses_a_chunk_bigger_than_igdb_can_answer():
    """Silently truncating would drop games the caller believes it fetched."""
    client = IGDBClient()
    with pytest.raises(ValueError, match="chunk the list"):
        await client.get_games_by_ids([str(i) for i in range(IGDB_PAGE_SIZE + 1)])


# ── 2. Mapping and the keyset walk ────────────────────────────────────────────


def test_enumeration_maps_rating_count_and_release_year():
    """``rating_count`` is the notoriety order; the epoch date becomes a year."""
    target = igdb_catalog.map_catalog_result(_catalog_row(4242, 900, 1_262_304_000))
    assert target is not None
    assert target.external_id == "4242"
    assert target.vote_count == 900
    assert target.release_year == 2010


def test_enumeration_survives_a_missing_or_broken_release_date():
    """A malformed date costs the year, not the target — the game still counts."""
    assert igdb_catalog.map_catalog_result(_catalog_row(1, 5, None)).release_year is None
    broken = igdb_catalog.map_catalog_result({"id": 2, "first_release_date": "nope"})
    assert broken is not None
    assert broken.release_year is None


def test_a_row_without_an_id_never_becomes_a_target():
    """No id means nothing to hydrate and nothing to link — it is dropped."""
    assert igdb_catalog.map_catalog_result({"rating_count": 900}) is None
    assert igdb_catalog.map_catalog_result({"id": 0}) is None


async def test_the_walk_advances_by_the_highest_id_seen():
    """Page 2 asks for ``id > <max id of page 1>``: the cursor is a real id."""
    pages = [
        [_catalog_row(10), _catalog_row(25), _catalog_row(31)],
        [_catalog_row(44), _catalog_row(58)],
    ]
    asked: list[int] = []
    emitted: list[str] = []

    async def fetch_page(after, limit):  # noqa: ARG001
        asked.append(after)
        return pages.pop(0) if pages else []

    async def sink(targets):
        emitted.extend(target.external_id for target in targets)

    stats = await igdb_catalog.enumerate_catalog(
        fetch_page=fetch_page, on_targets=sink, page_size=3, throttle_s=0
    )

    assert asked == [0, 31]  # a short second page ends the walk
    assert emitted == ["10", "25", "31", "44", "58"]
    assert stats.pages == 2
    assert stats.targets == 5
    assert stats.last_id == 58
    assert stats.stalled is False


async def test_the_walk_stops_and_reports_when_the_cursor_does_not_advance():
    """A page with no higher id cannot happen with ``sort id asc`` — and must not spin.

    Reported instead of swallowed: the list enumerated is then incomplete, and
    the CLI turns ``stalled`` into a non-zero exit code.
    """
    calls = 0

    async def fetch_page(after, limit):  # noqa: ARG001
        nonlocal calls
        calls += 1
        return [_catalog_row(7)] * limit

    stats = await igdb_catalog.enumerate_catalog(
        fetch_page=fetch_page, on_targets=AsyncMock(), page_size=1, throttle_s=0, start_after=7
    )

    assert calls == 1
    assert stats.stalled is True


async def test_the_walk_can_resume_after_a_given_id():
    """An interrupted enumeration restarts from a number it already knows."""
    asked: list[int] = []

    async def fetch_page(after, limit):  # noqa: ARG001
        asked.append(after)
        return []

    await igdb_catalog.enumerate_catalog(
        fetch_page=fetch_page, on_targets=AsyncMock(), throttle_s=0, start_after=123456
    )
    assert asked == [123456]


# ── 3. The persisted target list ──────────────────────────────────────────────


async def test_games_are_a_seed_target_source(db):
    """GAME/IGDB is registered, which is what wires the whole mechanism up."""
    assert SEED_TARGET_SOURCES["GAME"] == "IGDB"
    await upsert_seed_targets(db, [SeedTargetRow("GAME", "IGDB", "9090001", vote_count=300)])
    await db.flush()
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, _MAX_ATTEMPTS) == ["9090001"]


async def test_an_already_linked_game_is_not_re_enumerated_into_work(db):
    """A game the catalog holds drops out of the difference — and stays out.

    Two halves of the same acceptance criterion: the pending work list is a
    difference against ``external_ids`` (so a linked target is not work), and
    re-running the enumeration over it is an upsert that keeps its counters
    instead of resurrecting it.
    """
    game = _game("already-linked-90")
    db.add(game)
    await db.flush()
    await upsert_external_id(db, "GAME", game.id, "IGDB", "9090021")
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("GAME", "IGDB", "9090021", vote_count=900, release_year=2010),
            SeedTargetRow("GAME", "IGDB", "9090022", vote_count=800, release_year=2011),
        ],
    )
    await db.flush()

    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, _MAX_ATTEMPTS) == ["9090022"]

    # Re-enumerating both refreshes the observed values and adds no work.
    await mark_seed_targets_attempted(db, "GAME", "IGDB", ["9090022"], datetime.now(UTC))
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("GAME", "IGDB", "9090021", vote_count=950, release_year=2010),
            SeedTargetRow("GAME", "IGDB", "9090022", vote_count=850, release_year=2011),
        ],
    )
    await db.flush()

    rows = (
        await db.execute(
            text(
                "SELECT external_id, vote_count, attempts FROM seed_targets "
                "WHERE item_type = 'GAME' AND external_id IN ('9090021', '9090022') "
                "ORDER BY external_id"
            )
        )
    ).all()
    assert [(r.external_id, r.vote_count, r.attempts) for r in rows] == [
        ("9090021", 950, 0),
        ("9090022", 850, 1),
    ]
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, _MAX_ATTEMPTS) == ["9090022"]


async def test_game_targets_do_not_leak_across_item_types(db):
    """The same external id in two types is two different targets (issue #20)."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("GAME", "IGDB", "9090031", vote_count=100),
            SeedTargetRow("MOVIE", "TMDB", "9090031", vote_count=100),
        ],
    )
    await db.flush()
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, _MAX_ATTEMPTS) == ["9090031"]
    assert await get_pending_seed_targets(db, "GAME", "TMDB", 10, _MAX_ATTEMPTS) == []


async def test_progress_counters_work_for_games(db):
    """``pending`` / ``stuck`` mean for games exactly what they mean for movies."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("GAME", "IGDB", "9090041", vote_count=900),
            SeedTargetRow("GAME", "IGDB", "9090042", vote_count=800),
            SeedTargetRow("GAME", "IGDB", "9090043", vote_count=700),
        ],
    )
    now = datetime.now(UTC)
    await mark_seed_targets_unreachable(db, "GAME", "IGDB", ["9090042"], now)
    for _ in range(2):
        await mark_seed_targets_attempted(db, "GAME", "IGDB", ["9090043"], now)
    await db.flush()

    progress = await count_seed_target_progress(db, "GAME", "IGDB", 2)
    assert progress.total == 3
    assert progress.pending == 1
    assert progress.gone == 1
    assert progress.unlinkable == 1
    assert progress.stuck == 2
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, 2) == ["9090041"]


# ── 4. Target-driven hydration ────────────────────────────────────────────────


async def test_sync_games_fills_the_slice_with_pending_then_rotation(db):
    """One pending target plus one rotation item make up a slice of two."""
    stale = _game("stale-game-90", synced_days_ago=400)
    fresh = _game("fresh-game-90")
    db.add_all([stale, fresh])
    await db.flush()
    await upsert_external_id(db, "GAME", stale.id, "IGDB", "9090051")
    await upsert_external_id(db, "GAME", fresh.id, "IGDB", "9090052")
    await upsert_seed_targets(db, [SeedTargetRow("GAME", "IGDB", "9090053", vote_count=700)])
    await db.commit()

    requested: list[list[str]] = []

    async def fake_by_ids(ids):
        requested.append(list(ids))
        return [_igdb_game(int(i), f"Game {i}") for i in ids]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=fake_by_ids),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=2)

    # The pending target first, then the oldest catalog item — never the fresh one.
    assert requested == [["9090053", "9090051"]]
    assert result["synced"] == 2
    assert result["refreshed"] == 1
    assert result["pending"] == 0
    assert result["stuck"] == 0
    assert result["offset"] == 0
    assert result["people_errors"] == 0


async def test_sync_games_reads_no_sync_cursor(db):
    """``sync_cursors`` is out of the game path entirely (feature 90)."""
    with (
        patch("backlogg.scheduler.jobs.get_sync_offset", new_callable=AsyncMock) as get_cursor,
        patch("backlogg.scheduler.jobs.set_sync_offset", new_callable=AsyncMock) as set_cursor,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=5)

    get_cursor.assert_not_awaited()
    set_cursor.assert_not_awaited()
    assert result["offset"] == 0
    assert result["errors"] == 0


def test_seed_top_n_games_no_longer_exists():
    """The setting is *removed*, not left inert (unlike SEED_TOP_N_MOVIES).

    While it existed it was the wraparound target of a cursor shared with the
    backfill workflow, so it capped the game catalog at 10.000 of the ~31.988
    that pass the filter.  A name that used to do that is worth removing
    outright rather than leaving around to be re-wired by mistake.
    """
    assert not hasattr(settings, "SEED_TOP_N_GAMES")
    assert hasattr(settings, "SEED_TOP_N_BOOKS")  # still live for the book cursor


async def test_sync_games_retires_an_id_igdb_no_longer_serves(db):
    """An id missing from IGDB's answer is this source's 404: definitive.

    ``where id = (...)`` simply omits ids IGDB does not have.  Re-asking would
    spend a slice slot every run for an answer that will not change, and would
    hold ``pending`` above 0 forever — which is what stops the refresh rotation
    from ever firing.
    """
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("GAME", "IGDB", "9090061", vote_count=900),
            SeedTargetRow("GAME", "IGDB", "9090062", vote_count=800),
        ],
    )
    await db.commit()

    async def partial_answer(ids):
        return [_igdb_game(9090061, "Still There 90")]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=partial_answer),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=10)

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["pending"] == 0  # one linked, one retired
    assert result["stuck"] == 1
    row = (
        await db.execute(
            text("SELECT attempts, unreachable_at FROM seed_targets WHERE external_id = '9090062'")
        )
    ).one()
    assert row.unreachable_at is not None
    assert row.attempts == 0  # "gone" is a verdict, not a pass
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, _MAX_ATTEMPTS) == []


async def test_sync_games_counts_a_failed_request_without_burning_attempts(db):
    """IGDB being down costs an error, never a target's retirement budget."""
    await upsert_seed_targets(db, [SeedTargetRow("GAME", "IGDB", "9090071", vote_count=900)])
    await db.commit()

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_by_ids",
            new_callable=AsyncMock,
            side_effect=RuntimeError("igdb down"),
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=10)

    assert result["synced"] == 0
    assert result["errors"] == 1
    assert result["pending"] == 1  # still workable, retried next run for free
    row = (
        await db.execute(
            text("SELECT attempts, unreachable_at FROM seed_targets WHERE external_id = '9090071'")
        )
    ).one()
    assert row.attempts == 0
    assert row.unreachable_at is None


async def test_sync_games_reports_unknown_progress_when_the_work_list_fails(db):
    """A database outage must not report "catalog complete" as 0 pending."""
    with (
        patch(
            "backlogg.scheduler.jobs._read_seed_work_list",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games()

    assert result["errors"] == 1
    assert result["pending"] is None
    assert result["stuck"] is None


async def test_sync_games_chunks_the_work_list_by_igdb_page_size(db, monkeypatch):
    """A slice bigger than one IGDB response is split into successive requests."""
    monkeypatch.setattr(sync_jobs, "IGDB_PAGE_SIZE", 2)
    await upsert_seed_targets(
        db,
        [SeedTargetRow("GAME", "IGDB", str(9090080 + i), vote_count=900 - i) for i in range(5)],
    )
    await db.commit()

    chunks: list[list[str]] = []

    async def fake_by_ids(ids):
        chunks.append(list(ids))
        return [_igdb_game(int(i), f"Chunked {i}") for i in ids]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=fake_by_ids),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=5)

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert result["synced"] == 5
    assert result["pending"] == 0


# ── 5. The enumeration CLI ────────────────────────────────────────────────────
#
# ``scripts/`` is not an installed package, so the script is loaded by path —
# the same trick ``tests/test_backfill_sync.py`` uses.

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "seed_igdb_targets.py"
_spec = importlib.util.spec_from_file_location("seed_igdb_targets", _SCRIPT_PATH)
seed_igdb_targets = importlib.util.module_from_spec(_spec)
sys.modules["seed_igdb_targets"] = seed_igdb_targets
_spec.loader.exec_module(seed_igdb_targets)


def test_seed_cli_rejects_a_non_positive_page_size():
    with pytest.raises(SystemExit) as excinfo:
        seed_igdb_targets.main(["--page-size", "0"])
    assert excinfo.value.code != 0


def test_seed_cli_rejects_a_negative_resume_point():
    with pytest.raises(SystemExit) as excinfo:
        seed_igdb_targets.main(["--start-after", "-1"])
    assert excinfo.value.code != 0


def test_seed_cli_returns_two_when_the_walk_stalled():
    """An incomplete enumeration must not be reported as a green run."""
    summary = {
        "content_type": "game",
        "pages": 3,
        "enumerated": 1500,
        "last_id": 4242,
        "stalled": True,
        "targets_total": 1500,
        "targets_pending": 1500,
        "targets_stuck": 0,
    }
    with patch.object(seed_igdb_targets, "_amain", new_callable=AsyncMock, return_value=summary):
        assert seed_igdb_targets.main([]) == 2


def test_seed_cli_returns_one_on_an_unrecoverable_failure():
    with patch.object(
        seed_igdb_targets, "_amain", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ):
        assert seed_igdb_targets.main([]) == 1


def test_seed_cli_returns_zero_on_a_clean_run():
    summary = {
        "content_type": "game",
        "pages": 64,
        "enumerated": 31988,
        "last_id": 999999,
        "stalled": False,
        "targets_total": 31988,
        "targets_pending": 31988,
        "targets_stuck": 0,
    }
    with patch.object(
        seed_igdb_targets, "_amain", new_callable=AsyncMock, return_value=summary
    ) as mock_main:
        assert seed_igdb_targets.main(["--page-size", "500"]) == 0
    mock_main.assert_awaited_once_with(500, 0)


async def test_run_enumeration_persists_the_targets_it_finds(db):
    """End to end on the script: an IGDB page becomes rows in ``seed_targets``.

    This is the acceptance criterion "the enumeration produces targets", and
    the same run proves the other half of it: a game that does not clear the
    filter is never in the payload IGDB returns — the ``where`` excluded it —
    and a row with no id is dropped by the mapper instead of written.
    """
    pages = [
        [
            _catalog_row(9090091, 900, 1_262_304_000),
            _catalog_row(9090092, 40, None),
            {"rating_count": 500},  # no id: not a target
        ]
    ]

    async def fetch_page(self, after, limit):  # noqa: ARG001
        return pages.pop(0) if pages else []

    with (
        patch.object(IGDBClient, "get_catalog_page", new=fetch_page),
        patch.object(seed_igdb_targets, "async_session_factory", new=_mocked_session_factory(db)),
    ):
        summary = await seed_igdb_targets.run_enumeration(page_size=500, start_after=0)

    assert summary["pages"] == 1
    assert summary["enumerated"] == 2
    assert summary["stalled"] is False
    assert summary["targets_pending"] >= 2

    rows = (
        await db.execute(
            text(
                "SELECT external_id, source, vote_count, release_year FROM seed_targets "
                "WHERE item_type = 'GAME' AND external_id IN ('9090091', '9090092') "
                "ORDER BY external_id"
            )
        )
    ).all()
    assert [(r.external_id, r.source, r.vote_count, r.release_year) for r in rows] == [
        ("9090091", "IGDB", 900, 2010),
        ("9090092", "IGDB", 40, None),
    ]


# ── 5. The allowlist gate on hydration ────────────────────────────────────────
#
# The hydration query carries no ``game_type`` clause on purpose: adding one
# would make a game that *lost* its rating look like a 404 and get retired
# instead of refreshed.  That argument covers ``rating``, which moves on its
# own; it does not cover ``game_type``, which a reclassification can move
# between the enumeration and the hydration.  So the gate is re-applied on the
# payload, and these tests fix what it does on each side of the work list.


async def test_a_target_reclassified_out_of_the_allowlist_is_never_written(db):
    """Enumerated as a game, hydrated as a bundle: it does not enter (issue #14).

    The window is narrow but real — the enumeration's ``where`` decided hours
    or days earlier.  Without this gate the item would walk into the catalog
    past the allowlist the whole feature 65 path exists to enforce.
    """
    await upsert_seed_targets(db, [SeedTargetRow("GAME", "IGDB", "9090101", vote_count=900)])
    await db.commit()

    async def now_a_bundle(ids):
        return [_igdb_game(9090101, "Reclassified 90", game_type=3)]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=now_a_bundle),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=10)

    assert result["synced"] == 0
    assert result["errors"] == 0
    written = (
        await db.execute(text("SELECT count(*) FROM games WHERE slug = 'reclassified-90'"))
    ).scalar()
    assert written == 0

    # A conclusive pass, not a "gone": the id resolves, it is simply not
    # wanted.  It spends an attempt so it cannot cost a slice slot for ever,
    # and stays workable meanwhile in case the reclassification is undone.
    row = (
        await db.execute(
            text("SELECT attempts, unreachable_at FROM seed_targets WHERE external_id = '9090101'")
        )
    ).one()
    assert row.attempts == 1
    assert row.unreachable_at is None
    assert result["pending"] == 1


async def test_a_target_refused_by_the_allowlist_retires_after_its_attempts(db, monkeypatch):
    """It leaves the work list through the existing "resolves but never links" path."""
    monkeypatch.setattr(settings, "TMDB_SEED_MAX_ATTEMPTS", 1)
    await upsert_seed_targets(db, [SeedTargetRow("GAME", "IGDB", "9090102", vote_count=900)])
    await db.commit()

    async def now_a_pack(ids):
        return [_igdb_game(9090102, "Pack 90", game_type=13)]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=now_a_pack),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=10)

    assert result["synced"] == 0
    assert result["pending"] == 0
    assert result["stuck"] == 1
    assert await get_pending_seed_targets(db, "GAME", "IGDB", 10, 1) == []


async def test_a_catalog_item_reclassified_out_of_the_allowlist_is_refreshed_not_removed(db):
    """The gate stops entries; it does not evict.

    A row already in the catalog has user library entries, ratings and reviews
    pointing at it.  Deleting it as a side effect of a nightly refresh would
    take their data with it, and skipping the write would only freeze it on a
    stale payload — so the refresh happens, loudly logged.
    """
    held = _game("held-game-90", synced_days_ago=400)
    db.add(held)
    await db.flush()
    await upsert_external_id(db, "GAME", held.id, "IGDB", "9090103")
    await db.commit()

    async def now_a_bundle(ids):
        return [_igdb_game(9090103, "Held Game 90", game_type=3)]

    with (
        patch.object(sync_jobs._igdb_client, "get_games_by_ids", new=now_a_bundle),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=5)

    assert result["synced"] == 1
    assert result["refreshed"] == 1
    row = (
        await db.execute(text("SELECT game_type FROM games WHERE slug = 'held-game-90'"))
    ).one_or_none()
    assert row is not None  # still in the catalog
    assert row.game_type == "BUNDLE"  # and refreshed with what IGDB now says


async def test_the_gate_uses_the_same_allowlist_the_enumeration_does():
    """No second, drifting copy of the list — both read ``games.constants``."""
    assert 0 in ALLOWED_GAME_CATEGORY_IDS  # MAIN_GAME
    assert 3 not in ALLOWED_GAME_CATEGORY_IDS  # BUNDLE
    assert ALLOWED_GAME_TYPES == {GAME_TYPE_MAP[i] for i in ALLOWED_GAME_CATEGORY_IDS}


# ── 6. The hydration query's id list ──────────────────────────────────────────


async def test_get_games_by_ids_normalises_every_id_to_an_integer():
    """Apicalypse has no bound parameters, so the id list *is* interpolation.

    ``get_catalog_page`` already normalises its cursor with ``int``; this one
    did not, and the asymmetry is the kind that invites a mistake later.
    """
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_games_by_ids(["9090104", 9090105])

    _, body = mock_post.call_args.args
    assert " where id = (9090104,9090105);" in body


async def test_get_games_by_ids_refuses_a_non_numeric_id():
    """It fails loudly instead of letting whatever arrived reach the ``where``."""
    client = IGDBClient()
    with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
        with pytest.raises(ValueError, match="numeric IGDB id"):
            await client.get_games_by_ids(["1;drop"])
    mock_post.assert_not_awaited()
