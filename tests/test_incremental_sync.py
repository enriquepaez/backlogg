"""Tests for feature 88 — the IGDB, Open Library and orchestration half.

The TMDB half lives in ``tests/test_incremental_watermarks.py`` (the state
core) and ``tests/test_tmdb_incremental_updates.py`` (the three TMDB lanes).
What is proved here, in the order of the feature's acceptance list:

1. **IGDB carries the right temporal filter** — ``where created_at > <epoch>``
   and ``where updated_at > <epoch>``, with the ``game_type`` allowlist still
   in the clause, sorted ascending so the walk is resumable, and throttled at
   IGDB's 4 req/s between pages.
2. **A new game that fails the allowlist is not persisted** — the check the
   job owns, on the payload, not merely the clause a third party applies.
3. **The two IGDB watermarks advance independently** and one lane failing does
   not abort the other (checkpoint C19).
4. **The Open Library diff produces only what is new** and **never re-diffs an
   edition already covered** — the watermark is what stops a daily run from
   re-downloading 17,5 GB every night.
5. **The orchestrator isolates a failing source** and reports the run as
   degraded instead of green.

Everything that touches the database uses the real test database; IGDB, the
dump stream and the dump-edition lookup are always mocked, so nothing here
touches the network.
"""

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import func, select

from backlogg.books.adapters import openlibrary_dump as dump
from backlogg.books.models import Book
from backlogg.core.config import settings
from backlogg.games.adapters.igdb import (
    _PAGE_THROTTLE_S,
    IGDBClient,
    parse_igdb_timestamp,
)
from backlogg.games.constants import ALLOWED_GAME_CATEGORY_IDS
from backlogg.games.models import Game
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import get_sync_watermark, set_sync_watermark
from backlogg.shared.external_ids import ExternalId, upsert_external_id
from tests.books import dump_fixtures as fx

# ── Load the scripts as modules (scripts/ is not an installed package) ───────

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Order matters: ``incremental_sync`` imports ``seed_openlibrary_books`` as a
# sibling, and loading the seeding script first puts the *same* module object
# in ``sys.modules`` for both, so patching one patches what the other uses.
seed = _load_script("seed_openlibrary_books")
incremental = _load_script("incremental_sync")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mocked_session_factory(session):
    """Session factory whose context manager yields ``session``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _igdb_game(igdb_id: int, *, game_type: int = 0, created_at: int, updated_at: int) -> dict:
    """A raw IGDB game payload, shaped like the incremental query's field set."""
    return {
        "id": igdb_id,
        "name": f"Incremental Game {igdb_id}",
        "slug": f"incremental-game-{igdb_id}",
        "summary": "A brand new game.",
        "first_release_date": created_at,
        "rating": None,
        "rating_count": 0,
        "game_type": game_type,
        "genres": [],
        "platforms": [],
        "involved_companies": [],
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


async def _game_watermark(db, kind: str):
    return await get_sync_watermark(db, "IGDB", kind, "GAME")


# ═════════════════════════════════════════════════════════════════════════════
# 1. The IGDB query
# ═════════════════════════════════════════════════════════════════════════════


async def test_the_created_query_filters_on_created_at_and_keeps_the_allowlist():
    """``where created_at > <epoch>`` — and the category allowlist is still there.

    Both halves matter. Without the temporal filter this is the seeding query
    again; without the allowlist a bundle, a mod or a port would enter the
    catalog just for being new, which is exactly what feature 65 (issue #14)
    decided they must not do.
    """
    client = IGDBClient()
    since = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_games_created_since(since, limit=500)

    query = mock_post.await_args.args[1]
    assert f"created_at > {_epoch(since)}" in query
    allowlist = ",".join(str(i) for i in sorted(ALLOWED_GAME_CATEGORY_IDS))
    assert f"game_type = ({allowlist})" in query
    # Ascending, so the pages already read keep their offsets while new games
    # land at the end — that is what makes the walk resumable.
    assert "sort created_at asc;" in query
    # The ranking clause must NOT be here: a game released today has no rating,
    # so `rating > 0` would admit nothing at all.
    assert "rating > 0" not in query
    # The watermark is derived from these two fields, so they have to be asked for.
    assert "created_at,updated_at;" in query


async def test_the_updated_query_filters_on_updated_at():
    """The refresh lane asks the other question, with its own cut-off."""
    client = IGDBClient()
    since = datetime(2026, 8, 15, 6, 30, tzinfo=UTC)

    with patch.object(client, "_post", new_callable=AsyncMock, return_value=[]) as mock_post:
        await client.get_games_updated_since(since, limit=500)

    query = mock_post.await_args.args[1]
    assert f"updated_at > {_epoch(since)}" in query
    assert "sort updated_at asc;" in query
    assert "created_at >" not in query


async def test_the_incremental_query_paginates_and_throttles():
    """Beyond 500 it pages with ``offset``, sleeping IGDB's 4 req/s between pages."""
    client = IGDBClient()
    stamp = _epoch(datetime(2026, 9, 5, tzinfo=UTC))
    pages = [
        [_igdb_game(i, created_at=stamp, updated_at=stamp) for i in range(500)],
        [_igdb_game(500 + i, created_at=stamp, updated_at=stamp) for i in range(120)],
    ]

    with (
        patch.object(client, "_post", new_callable=AsyncMock, side_effect=pages) as mock_post,
        patch("backlogg.games.adapters.igdb.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        games = await client.get_games_created_since(datetime(2026, 9, 1, tzinfo=UTC), limit=1000)

    assert len(games) == 620
    offsets = [call.args[1] for call in mock_post.await_args_list]
    assert "offset 0;" in offsets[0]
    assert "offset 500;" in offsets[1]
    assert mock_sleep.await_args_list[0].args == (_PAGE_THROTTLE_S,)


@pytest.mark.parametrize("bad", [None, "not-a-number", object()])
def test_a_malformed_igdb_timestamp_is_none_not_an_exception(bad):
    """One broken field costs that game, never the page it arrived in."""
    assert parse_igdb_timestamp(bad) is None


def test_igdb_epoch_seconds_become_aware_datetimes():
    """C14: the epoch is converted explicitly, and always in UTC.

    ``set_sync_watermark`` rejects naive datetimes on purpose, so a conversion
    that dropped the timezone would surface as a crash in the lane rather than
    as a watermark quietly hours off.
    """
    converted = parse_igdb_timestamp(1_757_000_000)
    assert converted is not None
    assert converted.tzinfo is not None
    assert converted == datetime.fromtimestamp(1_757_000_000, tz=UTC)


# ═════════════════════════════════════════════════════════════════════════════
# 2. The allowlist gate on new games
# ═════════════════════════════════════════════════════════════════════════════


async def test_a_new_game_that_fails_the_allowlist_is_not_persisted(db, monkeypatch):
    """Being new is not a way in: a bundle stays out, a game goes in.

    The allowlist is in the IGDB ``where`` clause *and* re-checked here on the
    payload. This test exercises the second one, which is the one this codebase
    owns: it feeds the job a category IGDB should never have returned and
    proves the row still does not reach the catalog.
    """
    stamp = _epoch(datetime.now(UTC) - timedelta(hours=1))
    allowed = _igdb_game(880001, game_type=0, created_at=stamp, updated_at=stamp)
    bundle = _igdb_game(880002, game_type=3, created_at=stamp, updated_at=stamp)
    assert bundle["game_type"] not in ALLOWED_GAME_CATEGORY_IDS

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_created_since",
            new_callable=AsyncMock,
            return_value=[allowed, bundle],
        ),
        patch.object(
            sync_jobs._igdb_client,
            "get_games_updated_since",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games_incremental()

    created = result["new_games"]
    assert created["considered"] == 2
    assert created["gated_out"] == 1
    assert created["admitted"] == 1
    assert result["errors"] == 0

    links = set(
        (
            await db.execute(
                select(ExternalId.external_id).where(
                    ExternalId.item_type == "GAME",
                    ExternalId.source == "IGDB",
                    ExternalId.external_id.in_(["880001", "880002"]),
                )
            )
        ).scalars()
    )
    assert links == {"880001"}
    assert (
        await db.execute(
            select(func.count()).select_from(Game).where(Game.slug == "incremental-game-880002")
        )
    ).scalar_one() == 0


async def test_the_updated_lane_only_refreshes_games_the_catalog_holds(db, monkeypatch):
    """An ``updated_at`` bump is no argument for admitting an unknown game.

    The refresh lane's cost has to be proportional to the catalog, not to
    IGDB: without this rule every game IGDB touches would be pulled in, and the
    ranking bar that defines the game catalog would stop meaning anything.
    """
    stamp = _epoch(datetime.now(UTC) - timedelta(hours=2))
    known = _igdb_game(880101, created_at=stamp, updated_at=stamp)
    unknown = _igdb_game(880102, created_at=stamp, updated_at=stamp)

    game = Game(
        title="Known Game",
        slug="known-game-880101",
        game_type="MAIN_GAME",
        last_synced_at=datetime.now(UTC),
    )
    db.add(game)
    await db.flush()
    await upsert_external_id(db, "GAME", game.id, "IGDB", "880101")
    await db.flush()

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_created_since",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            sync_jobs._igdb_client,
            "get_games_updated_since",
            new_callable=AsyncMock,
            return_value=[known, unknown],
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games_incremental()

    updated = result["updated_games"]
    assert updated["considered"] == 2
    assert updated["unknown"] == 1
    assert updated["refreshed"] == 1

    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.item_type == "GAME", ExternalId.external_id == "880102")
        )
    ).scalar_one() == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3. The two IGDB watermarks
# ═════════════════════════════════════════════════════════════════════════════


async def test_the_two_igdb_watermarks_advance_independently(db, monkeypatch):
    """``CREATED_AT`` and ``UPDATED_AT`` are two rows, and they hold two facts.

    Each lane advances to the newest record *it* actually saw. Sharing one
    cursor would make the busier lane drag the quieter one forward over ground
    it never covered.
    """
    newest_created = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    newest_updated = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    created_rows = [
        _igdb_game(880201, created_at=_epoch(newest_created - timedelta(hours=1)), updated_at=1),
        _igdb_game(880202, created_at=_epoch(newest_created), updated_at=1),
    ]
    updated_rows = [_igdb_game(880203, created_at=1, updated_at=_epoch(newest_updated))]

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_created_since",
            new_callable=AsyncMock,
            return_value=created_rows,
        ),
        patch.object(
            sync_jobs._igdb_client,
            "get_games_updated_since",
            new_callable=AsyncMock,
            return_value=updated_rows,
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        await sync_jobs.sync_games_incremental()

    created_mark = await _game_watermark(db, "CREATED_AT")
    updated_mark = await _game_watermark(db, "UPDATED_AT")
    assert datetime.fromisoformat(created_mark.cursor_value) == newest_created
    assert datetime.fromisoformat(updated_mark.cursor_value) == newest_updated
    assert created_mark.cursor_value != updated_mark.cursor_value


async def test_the_created_lane_resumes_from_its_watermark(db, monkeypatch):
    """The next run asks IGDB for records newer than the persisted cursor.

    Also covers the cold-start bound: with no watermark the lane asks for the
    last ``IGDB_INCREMENTAL_LOOKBACK_DAYS`` and not for ``created_at > 0``,
    which would be IGDB's entire database.
    """
    covered = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    await set_sync_watermark(db, "IGDB", "CREATED_AT", "GAME", cursor_value=covered.isoformat())
    await db.flush()

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_created_since",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_created,
        patch.object(
            sync_jobs._igdb_client,
            "get_games_updated_since",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_updated,
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games_incremental()

    assert mock_created.await_args.args[0] == covered
    assert result["new_games"]["cold_start"] is False

    # The updated lane has no watermark yet: bounded cold start, not "since 0".
    assert result["updated_games"]["cold_start"] is True
    cold_since = mock_updated.await_args.args[0]
    lookback = timedelta(days=settings.IGDB_INCREMENTAL_LOOKBACK_DAYS)
    assert timedelta(0) < datetime.now(UTC) - cold_since <= lookback + timedelta(minutes=5)


async def test_a_failing_igdb_lane_does_not_abort_the_other(db, monkeypatch):
    """C19 — and the reason the two watermarks are separate rows."""
    stamp = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_games_created_since",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("igdb is down"),
        ),
        patch.object(
            sync_jobs._igdb_client,
            "get_games_updated_since",
            new_callable=AsyncMock,
            return_value=[_igdb_game(880301, created_at=1, updated_at=_epoch(stamp))],
        ),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs.sync_games_incremental()

    assert result["new_games"] == {"failed": True}
    assert result["errors"] == 1
    # The healthy lane ran to the end and moved its own mark.
    assert result["updated_games"]["considered"] == 1
    updated_mark = await _game_watermark(db, "UPDATED_AT")
    assert datetime.fromisoformat(updated_mark.cursor_value) == stamp
    # The failed lane's mark was never written, so tomorrow re-covers it.
    assert await _game_watermark(db, "CREATED_AT") is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. Open Library — the monthly dump diff
# ═════════════════════════════════════════════════════════════════════════════


def _edition_response(url: str, headers: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.url = url
    response.headers = headers or {}
    response.raise_for_status = MagicMock()
    return response


def _patch_edition_client(monkeypatch, response: MagicMock) -> None:
    """Make ``latest_dump_edition`` see ``response`` without a socket."""
    stream_cm = MagicMock()
    stream_cm.__enter__ = MagicMock(return_value=response)
    stream_cm.__exit__ = MagicMock(return_value=False)
    client = MagicMock()
    client.stream = MagicMock(return_value=stream_cm)
    client_cm = MagicMock()
    client_cm.__enter__ = MagicMock(return_value=client)
    client_cm.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(dump.httpx, "Client", MagicMock(return_value=client_cm))


def test_the_dump_edition_comes_from_the_redirected_url(monkeypatch):
    """``latest`` is an alias; the edition is in the URL it redirects to."""
    _patch_edition_client(
        monkeypatch,
        _edition_response(
            "https://ia903103.us.archive.org/12/items/ol_dump_2026-08-31/"
            "ol_dump_works_2026-08-31.txt.gz"
        ),
    )
    assert dump.latest_dump_edition() == date(2026, 8, 31)


def test_the_dump_edition_falls_back_to_last_modified(monkeypatch):
    """No date in the URL: the header is the documented fallback."""
    _patch_edition_client(
        monkeypatch,
        _edition_response(
            "https://openlibrary.org/data/ol_dump_works_latest.txt.gz",
            {"last-modified": "Mon, 31 Aug 2026 04:12:00 GMT"},
        ),
    )
    assert dump.latest_dump_edition() == date(2026, 8, 31)


def test_an_unidentifiable_dump_edition_raises_instead_of_guessing(monkeypatch):
    """Guessing would either redo a 2 h pass nightly or skip a real edition."""
    _patch_edition_client(
        monkeypatch, _edition_response("https://openlibrary.org/data/ol_dump_works_latest.txt.gz")
    )
    with pytest.raises(dump.DumpEditionUnknown):
        dump.latest_dump_edition()


# ── The diff itself ──────────────────────────────────────────────────────────


def _fixture_stream(name: str):
    streams = {
        dump.DUMP_READING_LOG: fx.reading_log_lines,
        dump.DUMP_EDITIONS: fx.edition_lines,
        dump.DUMP_WORKS: fx.work_lines,
        dump.DUMP_AUTHORS: fx.author_lines,
    }
    return iter(streams[name]())


def _patch_seed(db, monkeypatch, *, stream=_fixture_stream) -> None:
    monkeypatch.setattr(seed, "stream_dump_lines", stream)
    monkeypatch.setattr(seed, "async_session_factory", _mocked_session_factory(db))
    monkeypatch.setattr(seed, "engine", MagicMock(dispose=AsyncMock()))


async def test_the_dump_diff_writes_only_the_works_the_catalog_lacks(db, monkeypatch, tmp_path):
    """The diff of an edition against the catalog is what is *missing*, only.

    Two passes over the same fixture. The first finds an empty catalog and
    writes the four selected works; the second, run against the catalog the
    first one produced, writes nothing and reports all four as already known.
    That second number is the whole point of the mode: a monthly pass must not
    re-upsert 19 k unchanged rows to change nothing.
    """
    _patch_seed(db, monkeypatch)

    first = await seed.run(tmp_path / "2026-08-31", None, False, True)
    assert first["load"]["synced"] == 4
    assert first["load"]["already_known"] == 0

    second = await seed.run(tmp_path / "2026-09-30", None, False, True)
    assert second["load"]["already_known"] == 4
    assert second["load"]["synced"] == 0
    assert second["load"]["errors"] == 0

    # And the catalog still holds exactly one row per work — the diff neither
    # duplicated nor dropped anything.
    assert (
        await db.execute(
            select(func.count())
            .select_from(ExternalId)
            .where(ExternalId.item_type == "BOOK", ExternalId.source == "OPEN_LIBRARY")
        )
    ).scalar_one() == 4


async def test_the_dump_diff_admits_a_work_that_only_now_clears_the_filter(
    db, monkeypatch, tmp_path
):
    """A work already in the catalog is skipped; the rest still come in.

    This is the shape of a real monthly diff: most of the selection is already
    there, and what the pass is for is the handful that is not — new
    publications, and works that crossed the feature-73 thresholds since the
    previous dump.
    """
    _patch_seed(db, monkeypatch)

    existing = Book(
        title="Already Catalogued",
        slug="already-catalogued-88",
        last_synced_at=datetime.now(UTC),
    )
    db.add(existing)
    await db.flush()
    await upsert_external_id(db, "BOOK", existing.id, "OPEN_LIBRARY", fx.WORK_LOVE_HYPOTHESIS)
    await db.flush()

    summary = await seed.run(tmp_path / "2026-09-30", None, False, True)

    assert summary["load"]["already_known"] == 1
    assert summary["load"]["synced"] == 3
    # The pre-existing row was not re-written: refreshing is the nightly job's
    # business, not the monthly diff's.
    refreshed = (await db.execute(select(Book).where(Book.id == existing.id))).scalar_one()
    assert refreshed.title == "Already Catalogued"


async def test_an_edition_already_diffed_is_skipped_without_downloading(db, monkeypatch, tmp_path):
    """The watermark is what makes a *daily* run over a *monthly* dump cheap.

    On 29 days out of 30 the published edition is the one already covered, and
    the lane must stop at the edition lookup — one request, no body. The
    seeding pipeline is patched to explode precisely so that reaching it fails
    the test instead of quietly costing 17,5 GB.
    """
    edition = date(2026, 8, 31)
    await set_sync_watermark(
        db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK", cursor_value=edition.isoformat()
    )
    await db.flush()

    def _explode(*args, **kwargs):
        raise AssertionError("the dump pipeline must not run for an edition already diffed")

    with (
        patch.object(incremental, "latest_dump_edition", return_value=edition),
        patch.object(incremental, "ol_seed", MagicMock(run=_explode)),
        patch.object(incremental, "async_session_factory", _mocked_session_factory(db)),
    ):
        result = await incremental.run_book_incremental(tmp_path)

    assert result["skipped"] is True
    assert result["reason"] == "edition_already_diffed"
    assert result["edition"] == "2026-08-31"


async def test_a_new_edition_is_diffed_and_recorded(db, monkeypatch, tmp_path):
    """A new edition runs the pipeline once and then owns the watermark.

    The work dir is named after the edition, which is what makes resuming safe
    across runs: an artifact can only ever be reused by a run of the same
    edition.
    """
    previous = date(2026, 7, 31)
    published = date(2026, 8, 31)
    await set_sync_watermark(
        db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK", cursor_value=previous.isoformat()
    )
    await db.flush()

    seen: dict = {}

    async def _fake_run(work_dir, only, force, only_new):
        seen["work_dir"] = work_dir
        seen["only_new"] = only_new
        return {"load": {"candidates": 4, "already_known": 3, "synced": 1, "errors": 0}}

    with (
        patch.object(incremental, "latest_dump_edition", return_value=published),
        patch.object(incremental, "ol_seed", MagicMock(run=_fake_run)),
        patch.object(incremental, "async_session_factory", _mocked_session_factory(db)),
    ):
        result = await incremental.run_book_incremental(tmp_path)

    assert seen["only_new"] is True
    assert seen["work_dir"] == tmp_path / "2026-08-31"
    assert result["skipped"] is False
    assert result["previous_edition"] == "2026-07-31"
    assert result["synced"] == 1

    watermark = await get_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK")
    assert watermark.cursor_value == "2026-08-31"


async def test_an_edition_published_mid_pass_does_not_advance_the_watermark(
    db, monkeypatch, tmp_path
):
    """The alias is resolved twice, hours apart; if it moved, nothing is claimed.

    The pass names its work dir after the edition it resolved *before*
    downloading and then streams through the ``latest`` alias again. Should Open
    Library publish while the pass runs, that dir mixes editions — and the real
    damage would be advancing the watermark to an edition this run never
    diffed, which would skip it for a whole month. So the watermark stays put
    and the next run re-diffs the new edition from its own directory.
    """
    previous = date(2026, 7, 31)
    published = date(2026, 8, 31)
    newer = date(2026, 9, 30)
    await set_sync_watermark(
        db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK", cursor_value=previous.isoformat()
    )
    await db.flush()

    async def _fake_run(work_dir, only, force, only_new):
        return {"load": {"candidates": 4, "already_known": 3, "synced": 1, "errors": 0}}

    with (
        patch.object(incremental, "latest_dump_edition", side_effect=[published, newer]),
        patch.object(incremental, "ol_seed", MagicMock(run=_fake_run)),
        patch.object(incremental, "async_session_factory", _mocked_session_factory(db)),
    ):
        result = await incremental.run_book_incremental(tmp_path)

    assert result["edition"] == "2026-08-31"
    assert result["edition_changed_mid_run"] is True
    assert result["published_edition_after"] == "2026-09-30"

    watermark = await get_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK")
    assert watermark.cursor_value == "2026-07-31"


async def test_an_unanswerable_edition_recheck_still_records_the_pass(db, monkeypatch, tmp_path):
    """A flaky confirmation request must not throw away a finished 17,5 GB pass.

    The re-check exists to catch a once-a-month publication landing inside the
    run; a network error tells us nothing about that and is far more likely, so
    the lane keeps the behaviour it had before the check existed (advance) and
    says so in the log.
    """

    async def _fake_run(work_dir, only, force, only_new):
        return {"load": {"candidates": 1, "already_known": 0, "synced": 1, "errors": 0}}

    with (
        patch.object(
            incremental,
            "latest_dump_edition",
            side_effect=[date(2026, 8, 31), httpx.ConnectError("archive.org unreachable")],
        ),
        patch.object(incremental, "ol_seed", MagicMock(run=_fake_run)),
        patch.object(incremental, "async_session_factory", _mocked_session_factory(db)),
    ):
        result = await incremental.run_book_incremental(tmp_path)

    assert result["edition_changed_mid_run"] is False

    watermark = await get_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK")
    assert watermark.cursor_value == "2026-08-31"


async def test_a_dump_pass_that_dies_leaves_the_watermark_alone(db, monkeypatch, tmp_path):
    """A failed pass must be retried, not recorded as covered."""

    async def _boom(*args, **kwargs):
        raise httpx.ReadError("archive.org dropped the stream")

    with (
        patch.object(incremental, "latest_dump_edition", return_value=date(2026, 8, 31)),
        patch.object(incremental, "ol_seed", MagicMock(run=_boom)),
        patch.object(incremental, "async_session_factory", _mocked_session_factory(db)),
        pytest.raises(httpx.ReadError),
    ):
        await incremental.run_book_incremental(tmp_path)

    assert await get_sync_watermark(db, "OPEN_LIBRARY", "MONTHLY_DUMP", "BOOK") is None


# ═════════════════════════════════════════════════════════════════════════════
# 5. The orchestrator
# ═════════════════════════════════════════════════════════════════════════════


async def test_a_failing_source_does_not_abort_the_others(tmp_path):
    """C19 at the run level: one source down is not four sources down.

    The sources share nothing but the database and have independent watermarks
    by design, so a TMDB outage must not be the reason IGDB went a day without
    news.
    """
    calls: list[str] = []

    def _job(name: str, result: dict):
        async def _run():
            calls.append(name)
            return result

        return _run

    async def _failing_movies():
        calls.append("movie")
        raise httpx.ConnectError("tmdb is down")

    with (
        patch.object(incremental.jobs, "sync_movies_incremental", _failing_movies),
        patch.object(
            incremental.jobs, "sync_series_incremental", _job("series", {"synced": 2, "errors": 0})
        ),
        patch.object(
            incremental.jobs, "sync_games_incremental", _job("game", {"synced": 3, "errors": 0})
        ),
        patch.object(
            incremental,
            "run_book_incremental",
            AsyncMock(return_value={"skipped": True, "edition": "2026-08-31"}),
        ),
    ):
        summary = await incremental.run_incremental(list(incremental.SOURCES), tmp_path)

    assert calls == ["movie", "series", "game"]
    assert summary["failed"] == ["movie"]
    assert summary["sources"]["movie"]["failed"] is True
    assert "ConnectError" in summary["sources"]["movie"]["error"]
    assert summary["synced"] == 5
    # A run that lost a source is degraded, never green.
    assert incremental._exit_code(summary) == 2


async def test_a_clean_run_is_green_and_item_errors_are_not(tmp_path):
    """Exit 0 only when every source ran and nothing was rejected."""
    clean = {"synced": 1, "errors": 0}
    with (
        patch.object(incremental.jobs, "sync_movies_incremental", AsyncMock(return_value=clean)),
        patch.object(incremental.jobs, "sync_series_incremental", AsyncMock(return_value=clean)),
        patch.object(incremental.jobs, "sync_games_incremental", AsyncMock(return_value=clean)),
        patch.object(
            incremental, "run_book_incremental", AsyncMock(return_value={"skipped": True})
        ),
    ):
        summary = await incremental.run_incremental(list(incremental.SOURCES), tmp_path)

    assert summary["failed"] == []
    assert incremental._exit_code(summary) == 0

    # Item-level errors are degradation too: the catalog is less fresh than a
    # green run would claim.
    summary["errors"] = 3
    assert incremental._exit_code(summary) == 2


def test_the_cli_can_run_one_source_and_skip_another(tmp_path):
    """``--source``/``--skip`` decide the work list before anything runs."""
    seen: dict = {}

    async def _fake_amain(sources, work_dir, force):
        seen["sources"] = sources
        seen["work_dir"] = work_dir
        seen["force"] = force
        return {"failed": [], "errors": 0, "synced": 0, "elapsed_s": 0.0, "sources": {}}

    with patch.object(incremental, "_amain", _fake_amain):
        code = incremental.main(["--source", "game", "--work-dir", str(tmp_path)])
    assert code == 0
    assert seen["sources"] == ["game"]
    assert seen["work_dir"] == tmp_path

    with patch.object(incremental, "_amain", _fake_amain):
        incremental.main(["--skip", "book"])
    assert seen["sources"] == ["movie", "series", "game"]


def test_the_cli_reports_a_degraded_run_as_exit_2():
    """The exit code is what the workflow reads; a lost source must show."""

    async def _degraded(sources, work_dir, force):
        return {
            "failed": ["book"],
            "errors": 0,
            "synced": 0,
            "elapsed_s": 0.0,
            "sources": {"book": {"failed": True}},
        }

    with patch.object(incremental, "_amain", _degraded):
        assert incremental.main([]) == 2


def test_the_cli_reports_an_unrunnable_run_as_exit_1():
    """A run that could not be made at all is red, not degraded."""

    async def _boom(sources, work_dir, force):
        raise RuntimeError("no database")

    with patch.object(incremental, "_amain", _boom):
        assert incremental.main([]) == 1
