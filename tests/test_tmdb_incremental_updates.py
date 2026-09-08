"""Tests for feature 88 — the TMDB half of ``catalog_incremental_updates``.

What is under test, in the order of the feature's acceptance list:

1. **The daily id export** — the URL and the 08:00 UTC publication rule, the
   gzip stream decoded straight off the socket, and above all *the diff*: the
   ids of today's file that were not in the baseline and are not known
   locally, and **only** those.
2. **``/movie/changes`` and ``/tv/changes``** — the query the adapter builds,
   the 100-per-page pagination, and that a range longer than 14 days is sliced
   into windows that are never longer than 14 days.
3. **The release gate** — the entry rule for ids that have no ``vote_count``
   yet.  Including the one that matters most: *a new item that does not clear
   the gate is not persisted.*
4. **The promotion sweep** — the regression test the acceptance list asks for
   by name: an item that was below the threshold and crosses it ends up in the
   catalog with no manual intervention.
5. **The watermarks** — cold start, a gap wider than the export retention, a
   failed fetch holding the mark back, and a lane failure not taking the other
   two down with it (checkpoint C19).

Every test that touches the database uses the real test database; TMDB is
always mocked, at the ``httpx`` layer, so nothing here touches the network.
"""

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import text

from backlogg.core.config import settings
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.models import Movie
from backlogg.scheduler import discovery
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler import tmdb_exports as exports
from backlogg.scheduler.repository import (
    SeedTargetRow,
    count_seed_targets,
    get_sync_watermark,
    set_sync_watermark,
    upsert_seed_targets,
)
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.shared.external_ids import upsert_external_id

_SOURCE = "TMDB"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _json_response(payload: dict) -> MagicMock:
    """Minimal stand-in for a 200 httpx.Response."""
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock()
    return response


def _mocked_session_factory(session):
    """Session factory whose context manager yields ``session``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _export_body(rows: list[dict]) -> bytes:
    """A daily id export: gzipped JSONL, one object per line."""
    return gzip.compress("\n".join(json.dumps(row) for row in rows).encode() + b"\n")


def _export_row(tmdb_id: int, **overrides) -> dict:
    row = {
        "adult": False,
        "id": tmdb_id,
        "original_title": f"Export Title {tmdb_id}",
        "popularity": 1.0,
        "video": False,
    }
    row.update(overrides)
    return row


def _patch_export_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Route the export module's ``httpx.Client`` through a mock transport."""
    original_client = httpx.Client

    def patched_client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(exports.httpx, "Client", patched_client)


def _movie_detail(tmdb_id: int, **overrides) -> dict:
    """A TMDB movie detail payload that clears the release gate by default."""
    detail = {
        "id": tmdb_id,
        "title": f"Incremental Movie {tmdb_id}",
        "original_title": f"Incremental Movie {tmdb_id}",
        "overview": "A brand new release.",
        "release_date": date.today().isoformat(),
        "runtime": 99,
        "original_language": "en",
        "poster_path": "/poster.jpg",
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "adult": False,
        "video": False,
        "vote_average": 0,
        "vote_count": 0,
        "genres": [],
        "credits": {"cast": [], "crew": []},
        "external_ids": {},
    }
    detail.update(overrides)
    return detail


def _movie_gate() -> discovery.ReleaseGate:
    return discovery.ReleaseGate(
        date_key="release_date",
        max_age_days=90,
        horizon_days=180,
        rejected_statuses=frozenset({"Rumored", "Canceled"}),
    )


# ── 1. The daily id export ────────────────────────────────────────────────────


def test_export_url_uses_the_month_day_year_filename():
    """TMDB names the files MM_DD_YYYY, zero padded."""
    assert exports.export_url(exports.EXPORT_MOVIES, date(2026, 9, 8)) == (
        "https://files.tmdb.org/p/exports/movie_ids_09_08_2026.json.gz"
    )
    assert exports.export_url(exports.EXPORT_SERIES, date(2026, 12, 31)) == (
        "https://files.tmdb.org/p/exports/tv_series_ids_12_31_2026.json.gz"
    )


def test_latest_export_date_waits_for_the_publication_hour():
    """The file for a day is only served from ~08:00 UTC; before that, yesterday."""
    assert exports.latest_export_date(datetime(2026, 9, 8, 7, 59, tzinfo=UTC)) == date(2026, 9, 7)
    assert exports.latest_export_date(datetime(2026, 9, 8, 8, 0, tzinfo=UTC)) == date(2026, 9, 8)
    assert exports.latest_export_date(datetime(2026, 9, 8, 23, 30, tzinfo=UTC)) == date(2026, 9, 8)


def test_latest_export_date_reads_the_publication_hour_in_utc():
    """09:30 in Madrid is 07:30 UTC — the file is not out yet."""
    madrid = datetime(2026, 9, 8, 9, 30, tzinfo=UTC) - timedelta(hours=2)
    local = madrid.astimezone(UTC).replace(tzinfo=UTC)
    assert exports.latest_export_date(local) == date(2026, 9, 7)


def test_latest_export_date_rejects_a_naive_datetime():
    """A naive clock is how a nightly job asks for a file that does not exist yet."""
    with pytest.raises(ValueError, match="timezone-aware"):
        exports.latest_export_date(datetime(2026, 9, 8, 12, 0))  # noqa: DTZ001


def test_stream_export_lines_decompresses_the_response_on_the_fly(monkeypatch):
    """The 28 MB gzip is decoded straight off the socket, never through disk."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=_export_body([_export_row(1), _export_row(2)]))

    _patch_export_client(monkeypatch, httpx.MockTransport(handler))

    entries = list(exports.stream_export_entries(exports.EXPORT_MOVIES, date(2026, 9, 8)))
    assert [entry.external_id for entry in entries] == ["1", "2"]
    assert seen["url"] == exports.export_url(exports.EXPORT_MOVIES, date(2026, 9, 8))


def test_stream_export_lines_raises_export_unavailable_on_404(monkeypatch):
    """A missing file is an answer, not a failure: it never burns the retry budget."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, content=b"")

    _patch_export_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(exports.ExportUnavailable):
        list(exports.stream_export_lines(exports.EXPORT_MOVIES, date(2020, 1, 1)))
    assert calls["n"] == 1


def test_stream_export_lines_retries_a_connection_lost_before_any_data(monkeypatch):
    """Reopening the stream costs nothing, so a failure before the first line is redone."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset by peer", request=request)
        return httpx.Response(200, content=_export_body([_export_row(7)]))

    _patch_export_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(exports, "_EXPORT_RETRY_BACKOFF_S", 0)

    entries = list(exports.stream_export_entries(exports.EXPORT_MOVIES, date(2026, 9, 8)))
    assert [entry.external_id for entry in entries] == ["7"]
    assert calls["n"] == 2


def test_parse_export_line_reads_both_title_fields_and_skips_junk():
    """``original_title`` for movies, ``original_name`` for series."""
    movie = exports.parse_export_line(json.dumps(_export_row(11, popularity=3.5)))
    assert movie is not None
    assert (movie.external_id, movie.title, movie.popularity) == ("11", "Export Title 11", 3.5)

    series = exports.parse_export_line(json.dumps({"id": 12, "original_name": "Serie"}))
    assert series is not None
    assert (series.external_id, series.title) == ("12", "Serie")

    assert exports.parse_export_line("") is None
    assert exports.parse_export_line("{not json") is None
    assert exports.parse_export_line(json.dumps({"original_title": "no id"})) is None


def test_the_daily_diff_produces_only_the_new_ids(monkeypatch):
    """Acceptance: the diff of the id file yields the ids that *appeared* — only those.

    Three subtractions in one assertion, because all three are what makes the
    result mean "new release" instead of "everything we do not have":

    * ``1`` and ``2`` are in the baseline file — not new to TMDB;
    * ``3`` appeared but is already known locally (catalogued or queued);
    * ``4`` is the only genuine novelty;
    * ``5`` and ``6`` appeared too and are dropped as ``adult``/``video``,
      mirroring the two flags the ``/discover`` enumeration sets to false.
    """
    baseline_day = date(2026, 9, 7)
    today_day = date(2026, 9, 8)
    files = {
        exports.export_url(exports.EXPORT_MOVIES, baseline_day): _export_body(
            [_export_row(1), _export_row(2)]
        ),
        exports.export_url(exports.EXPORT_MOVIES, today_day): _export_body(
            [
                _export_row(1),
                _export_row(2),
                _export_row(3),
                _export_row(4, popularity=9.0),
                _export_row(5, adult=True),
                _export_row(6, video=True),
            ]
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=files[str(request.url)])

    _patch_export_client(monkeypatch, httpx.MockTransport(handler))

    baseline_ids = exports.load_export_ids(exports.EXPORT_MOVIES, baseline_day)
    assert baseline_ids == {"1", "2"}

    appeared = exports.collect_appeared_entries(
        exports.EXPORT_MOVIES,
        today_day,
        baseline_ids=baseline_ids,
        known_ids={"3"},
    )
    assert [entry.external_id for entry in appeared] == ["4"]


def test_the_daily_diff_orders_the_new_ids_by_popularity(monkeypatch):
    """A truncated or interrupted run must have spent its requests on the best ids."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_export_body(
                [
                    _export_row(20, popularity=0.5),
                    _export_row(21, popularity=12.0),
                    _export_row(22, popularity=4.0),
                ]
            ),
        )

    _patch_export_client(monkeypatch, httpx.MockTransport(handler))

    appeared = exports.collect_appeared_entries(
        exports.EXPORT_MOVIES, date(2026, 9, 8), baseline_ids=set(), known_ids=set()
    )
    assert [entry.external_id for entry in appeared] == ["21", "22", "20"]


async def test_get_known_source_ids_unions_catalog_and_targets(db):
    """ "Known" is both halves: catalogued *and* enumerated-but-not-hydrated."""
    movie = Movie(title="Known", slug="known-2026-88", last_synced_at=datetime.now(UTC))
    db.add(movie)
    await db.flush()
    await upsert_external_id(db, "MOVIE", movie.id, _SOURCE, "880001")
    await upsert_seed_targets(db, [SeedTargetRow("MOVIE", _SOURCE, "880002", 30, 2026)])
    await db.flush()

    known = await sync_jobs.get_known_source_ids(db, "MOVIE", _SOURCE)
    assert {"880001", "880002"} <= known
    assert "880003" not in known


# ── 2. /changes: the query, the pagination and the 14-day window ─────────────


async def test_get_movie_changes_page_builds_the_window_query():
    client = TMDBClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_json_response({"results": [], "page": 1, "total_pages": 1}),
    ) as mock_get:
        await client.get_movie_changes_page(
            page=2, start_date=date(2026, 9, 1), end_date=date(2026, 9, 14)
        )

    assert mock_get.call_args.args[0].endswith("/movie/changes")
    assert mock_get.call_args.kwargs["params"] == {
        "page": 2,
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
    }


async def test_get_series_changes_page_builds_the_window_query():
    client = TMDBSeriesClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_json_response({"results": [], "page": 1, "total_pages": 1}),
    ) as mock_get:
        await client.get_series_changes_page(
            page=1, start_date=date(2026, 9, 1), end_date=date(2026, 9, 14)
        )

    assert mock_get.call_args.args[0].endswith("/tv/changes")
    assert mock_get.call_args.kwargs["params"]["start_date"] == "2026-09-01"


async def test_fetch_change_ids_walks_every_page_and_deduplicates():
    """100 ids per page, and an item changed twice is hydrated once."""
    requested: list[int] = []

    async def fetch_page(*, page: int, start_date: date, end_date: date) -> dict:
        requested.append(page)
        return {
            "page": page,
            "total_pages": 3,
            "results": [{"id": 100 + page}, {"id": 200}, {"id": None}],
        }

    window = discovery.DateWindow("w", date(2026, 9, 1), date(2026, 9, 14))
    feed = await discovery.fetch_change_ids(window, fetch_page=fetch_page, concurrency=2)

    assert sorted(requested) == [1, 2, 3]
    assert feed.ids == ["101", "200", "102", "103"]
    # Under the cap: one window walked whole, nothing truncated, and the whole
    # span is covered — the caller may move the watermark to window.end.
    assert feed.windows == 1
    assert feed.truncated_labels == []
    assert feed.covered_through == date(2026, 9, 14)


def test_a_changes_range_longer_than_14_days_is_split():
    """Acceptance: a window over 14 days is chunked, with no overlap and no hole."""
    windows = discovery.change_windows(date(2026, 8, 1), date(2026, 9, 9))

    assert len(windows) == 3
    assert [(w.start, w.end) for w in windows] == [
        (date(2026, 8, 1), date(2026, 8, 14)),
        (date(2026, 8, 15), date(2026, 8, 28)),
        (date(2026, 8, 29), date(2026, 9, 9)),
    ]
    assert all((w.end - w.start).days + 1 <= discovery.MAX_CHANGES_WINDOW_DAYS for w in windows)


def test_the_changes_page_cap_is_the_same_500_as_discover():
    """``/changes`` is not exempt: page 501 answers HTTP 400 there too.

    Measured against the live API on 2026-09-08: ``/movie/changes`` over
    2026-08-26..2026-09-08 reports 746 pages / 74.593 results, a single day 73
    pages / 7.237 results, ``/tv/changes`` 163 pages for the same 13 days.  So
    the guard is reused, not re-invented — one constant, one cap.
    """
    assert discovery.MAX_DISCOVER_PAGES == 500


async def test_a_changes_window_over_the_page_cap_is_split_into_sub_windows(monkeypatch):
    """A window whose page 1 declares too many pages is halved and re-walked.

    The regression this pins: a 14-day movie window declares ~1.000 pages, so
    walking ``total_pages`` blindly asked for ``page=501`` and got an HTTP 400
    on the very first production run.
    """
    # Lower the cap instead of faking 500 pages: same code path, fast test.
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    requested: list[tuple[date, date, int]] = []

    async def fetch_page(*, page: int, start_date: date, end_date: date) -> dict:
        requested.append((start_date, end_date, page))
        if (start_date, end_date) == (date(2026, 9, 1), date(2026, 9, 14)):
            return {"page": page, "total_pages": 8, "results": [{"id": 1}]}  # over the cap
        return {"page": page, "total_pages": 1, "results": [{"id": start_date.day}]}

    window = discovery.change_windows(date(2026, 9, 1), date(2026, 9, 14))[0]
    feed = await discovery.fetch_change_ids(window, fetch_page=fetch_page, concurrency=2)

    # The full window is probed once (that is how the cap is detected) and then
    # each half is walked on its own.
    assert requested == [
        (date(2026, 9, 1), date(2026, 9, 14), 1),
        (date(2026, 9, 1), date(2026, 9, 7), 1),
        (date(2026, 9, 8), date(2026, 9, 14), 1),
    ]
    assert feed.windows == 2
    assert feed.ids == ["1", "8"]  # the two halves, chronological order kept
    assert feed.truncated_labels == []
    # Split, not truncated: the whole span was still covered.
    assert feed.covered_through == date(2026, 9, 14)


async def test_the_changes_split_stops_at_the_one_day_floor(monkeypatch):
    """The recursion bottoms out at one day — /changes has no finer granularity."""
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    requested: list[tuple[date, date, int]] = []

    async def fetch_page(*, page: int, start_date: date, end_date: date) -> dict:
        requested.append((start_date, end_date, page))
        # Every window saturates, however small: the split must still stop.
        return {"page": page, "total_pages": 9, "results": [{"id": f"{start_date}-{page}"}]}

    window = discovery.change_windows(date(2026, 9, 1), date(2026, 9, 4))[0]
    feed = await discovery.fetch_change_ids(window, fetch_page=fetch_page, concurrency=2)

    leaves = [(start, end) for start, end, page in requested if page == 1 and start == end]
    assert leaves == [(date(2026, 9, day), date(2026, 9, day)) for day in (1, 2, 3, 4)]
    # No day is asked for twice and none is skipped.
    assert feed.windows == 4
    assert feed.truncated_labels == [f"2026-09-0{day}..2026-09-0{day}" for day in (1, 2, 3, 4)]
    # Never past the cap, on any window.
    assert max(page for _, _, page in requested) == 2
    # Not one day was covered whole, so the caller may not move the watermark.
    assert feed.covered_through is None


async def test_a_single_day_over_the_cap_is_reported_not_raised(monkeypatch):
    """The floor case: take the pages TMDB serves, report the day, do not blow up."""
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    pages_fetched: list[int] = []

    async def fetch_page(*, page: int, start_date: date, end_date: date) -> dict:  # noqa: ARG001
        pages_fetched.append(page)
        return {"page": page, "total_pages": 7, "results": [{"id": 900 + page}]}

    window = discovery.change_windows(date(2026, 9, 3), date(2026, 9, 3))[0]
    feed = await discovery.fetch_change_ids(window, fetch_page=fetch_page, concurrency=2)

    assert sorted(pages_fetched) == [1, 2]  # capped, not 7 — and never 501
    assert feed.ids == ["901", "902"]  # a partial refresh beats none
    assert feed.truncated_labels == ["2026-09-03..2026-09-03"]
    assert feed.truncated_windows == 1
    # Reported as an uncovered stretch, exactly like the retention gap.
    assert feed.covered_through is None


async def test_the_watermark_does_not_advance_past_a_saturated_day(db, monkeypatch):
    """A day that saturates the cap stops the mark on the day before it.

    Three days planned; the middle one declares more pages than the cap and
    cannot be split further.  The honest outcome is that the first day is
    covered, the mark stands there, and the run reports the saturated day
    instead of claiming the window.
    """
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=3)
    saturated_day = today - timedelta(days=2)
    await set_sync_watermark(db, _SOURCE, "CHANGES", "MOVIE", cursor_value=first_day.isoformat())
    await db.commit()

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        params = kwargs["params"]
        start = date.fromisoformat(params["start_date"])
        end = date.fromisoformat(params["end_date"])
        over_cap = start <= saturated_day <= end
        return _json_response(
            {"page": params["page"], "total_pages": 9 if over_cap else 1, "results": []}
        )

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_changes(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["truncated_windows"] == 1
    assert result["truncated_labels"] == [
        f"{saturated_day.isoformat()}..{saturated_day.isoformat()}"
    ]
    # Covered through the day *before* the hole, and not one day further.
    assert result["covered_through"] == first_day.isoformat()
    assert result["windows_covered"] == 0  # the window was not covered whole
    watermark = await get_sync_watermark(db, _SOURCE, "CHANGES", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == first_day.isoformat()


async def test_the_changes_lane_never_asks_for_more_than_14_days(db):
    """A watermark 40 days old is not requested as a 40-day window.

    TMDB keeps 14 days of change history and answers 14 days per request, so
    the honest plan is: request the 14 days it still has, and report the rest
    as uncovered rather than pretend the catalog was refreshed.
    """
    today = datetime.now(UTC).date()
    await set_sync_watermark(
        db,
        _SOURCE,
        "CHANGES",
        "MOVIE",
        cursor_value=(today - timedelta(days=40)).isoformat(),
    )
    await db.flush()

    windows: list[tuple[str, str]] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        params = kwargs["params"]
        windows.append((params["start_date"], params["end_date"]))
        return _json_response({"page": 1, "total_pages": 1, "results": []})

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_changes(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert len(windows) == 1
    start, end = windows[0]
    assert (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 == 14
    # 40 days back is the last day *covered*, so the gap is the 26 days between
    # it and the retention horizon — not 27: the watermark day is not a hole.
    assert result["uncovered_days"] == 26
    assert result["covered_through"] == today.isoformat()


async def test_the_changes_lane_refreshes_only_what_is_already_in_the_catalog(db):
    """``/changes`` carries no quality signal, so it can refresh but never admit."""
    movie = Movie(
        title="Already Catalogued",
        slug="already-catalogued-2020-88",
        last_synced_at=datetime.now(UTC) - timedelta(days=200),
    )
    db.add(movie)
    await db.flush()
    await upsert_external_id(db, "MOVIE", movie.id, _SOURCE, "880101")
    await db.commit()

    fetched: list[str] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        if "/movie/changes" in url:
            return _json_response(
                {"page": 1, "total_pages": 1, "results": [{"id": 880101}, {"id": 880102}]}
            )
        tmdb_id = int(url.rsplit("/", 1)[-1])
        fetched.append(str(tmdb_id))
        return _json_response(_movie_detail(tmdb_id, title="Refreshed Title"))

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_changes(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert fetched == ["880101"], "the unknown id must not even be fetched"
    assert result["changed_ids"] == 2
    assert result["in_catalog"] == 1
    assert result["refreshed"] == 1

    # The unknown id did not enter the catalog through this door.
    unknown = (
        await db.execute(
            text("SELECT COUNT(*) FROM external_ids WHERE external_id = '880102'"),
        )
    ).scalar_one()
    assert unknown == 0

    watermark = await get_sync_watermark(db, _SOURCE, "CHANGES", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == datetime.now(UTC).date().isoformat()


async def test_a_failed_changes_window_does_not_advance_the_watermark(db):
    """ "The mark moved" has to keep meaning "that range was covered"."""

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("TMDB is down")

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_changes(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["errors"] == 1
    assert result["covered_through"] is None
    assert await get_sync_watermark(db, _SOURCE, "CHANGES", "MOVIE") is None


# ── 3. The release gate ───────────────────────────────────────────────────────


def test_the_release_gate_admits_a_recent_release():
    """A dated, described, non-adult release from today clears every check."""
    assert (
        discovery.release_gate_verdict(_movie_detail(1), gate=_movie_gate(), today=date.today())
        is None
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        # The two date-window reasons are expressed as offsets from today, not
        # as absolute dates: the gate's window (90 days back, 180 ahead) moves
        # with the calendar, so a hardcoded "2031-01-01" stops meaning
        # "too far ahead" once the suite is run in 2030.
        ({"release_date": (date.today() - timedelta(days=400)).isoformat()}, "too_old"),
        ({"release_date": (date.today() + timedelta(days=400)).isoformat()}, "too_far_ahead"),
        ({"release_date": ""}, "no_release_date"),
        ({"release_date": "not-a-date"}, "unparseable_release_date"),
        ({"adult": True}, "adult"),
        ({"video": True}, "video"),
        ({"status": "Rumored"}, "status:Rumored"),
        ({"status": "Canceled"}, "status:Canceled"),
        ({"title": ""}, "no_title"),
        ({"poster_path": None, "overview": ""}, "no_poster_or_overview"),
    ],
)
def test_the_release_gate_rejects_and_says_why(overrides, reason):
    """Each rejection is named, so a gate that rejects everything is visible."""
    detail = _movie_detail(1, **overrides)
    assert discovery.release_gate_verdict(detail, gate=_movie_gate(), today=date.today()) == reason


def test_the_series_gate_does_not_reject_a_cancelled_series():
    """ "Canceled" on a series means "aired and then dropped" — a real catalog item."""
    gate = discovery.ReleaseGate(
        date_key="first_air_date",
        max_age_days=90,
        horizon_days=180,
        rejected_statuses=frozenset(),
    )
    detail = {
        "name": "Cancelled After One Season",
        "overview": "Aired, then dropped.",
        "first_air_date": date.today().isoformat(),
        "status": "Canceled",
    }
    assert discovery.release_gate_verdict(detail, gate=gate, today=date.today()) is None


async def test_a_new_item_that_fails_the_quality_filter_is_not_persisted(db, monkeypatch):
    """Acceptance: a new id that does not clear the gate never reaches the catalog.

    Both ids appear in today's export.  ``880201`` is a release from today;
    ``880202`` is a 1979 title someone just created a record for — a *new id*
    but not a *new item*, which is exactly the material the ``vote_count``
    threshold keeps out of the seeded catalog.
    """
    today = datetime.now(UTC).date()
    monkeypatch.setattr(sync_jobs, "load_export_ids", lambda name, day: {"880000"}, raising=True)
    monkeypatch.setattr(
        sync_jobs,
        "collect_appeared_entries",
        lambda name, day, *, baseline_ids, known_ids: [
            exports.ExportEntry("880201", "New Release", 9.0, False, False),
            exports.ExportEntry("880202", "Old Catalogue Entry", 0.1, False, False),
        ],
        raising=True,
    )
    await set_sync_watermark(
        db,
        _SOURCE,
        "DAILY_ID_EXPORT",
        "MOVIE",
        cursor_value=(today - timedelta(days=1)).isoformat(),
    )
    await db.commit()

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        tmdb_id = int(url.rsplit("/", 1)[-1])
        if tmdb_id == 880202:
            return _json_response(_movie_detail(tmdb_id, release_date="1979-05-04"))
        return _json_response(_movie_detail(tmdb_id))

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_new_releases(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["appeared"] == 2
    assert result["admitted"] == 1
    assert result["gated_out"] == 1
    assert result["gate_reasons"] == {"too_old": 1}

    linked = (
        await db.execute(
            text("SELECT external_id FROM external_ids WHERE item_type = 'MOVIE' ORDER BY 1")
        )
    ).scalars()
    assert list(linked) == ["880201"]
    titles = (
        await db.execute(text("SELECT title FROM movies WHERE title LIKE 'Incremental Movie%'"))
    ).scalars()
    assert list(titles) == ["Incremental Movie 880201"]

    watermark = await get_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == exports.latest_export_date(datetime.now(UTC)).isoformat()


# ── 4. The promotion sweep ────────────────────────────────────────────────────


async def test_an_item_that_crosses_the_threshold_reaches_the_catalog(db, monkeypatch):
    """Acceptance regression: promotion needs no manual intervention.

    ``880301`` was below ``vote_count >= 25`` when the catalog was seeded, so
    it is in neither ``seed_targets`` nor ``external_ids``.  It has since
    crossed the threshold, so ``/discover`` now returns it.  The promotion
    sweep enumerates it and the ordinary nightly hydration — untouched by this
    feature — puts it in the catalog.
    """
    # Two years, so the sweep produces two windows and the same id is
    # enumerated in both: that is what makes the de-duplication below
    # ("enumerated 2, one seed target") an assertion and not a coincidence.
    monkeypatch.setattr(settings, "TMDB_PROMOTION_YEARS", 2)
    assert await count_seed_targets(db, "MOVIE", _SOURCE) == 0

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        if "/discover/movie" in url:
            return _json_response(
                {
                    "page": 1,
                    "total_pages": 1,
                    "total_results": 1,
                    "results": [
                        {"id": 880301, "vote_count": 30, "release_date": "2026-02-01"},
                    ],
                }
            )
        tmdb_id = int(url.rsplit("/", 1)[-1])
        return _json_response(_movie_detail(tmdb_id, release_date="2026-02-01", vote_count=30))

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        promotion = await sync_jobs._incremental_promotion(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )
        assert promotion["enumerated"] == 2  # one window per year, same id in both
        assert await count_seed_targets(db, "MOVIE", _SOURCE) == 1

        # No manual step in between: the nightly job picks the new target up.
        hydration = await sync_jobs.sync_movies(slice_size=5)

    assert hydration["synced"] == 1
    assert hydration["pending"] == 0
    linked = (
        await db.execute(
            text("SELECT item_id FROM external_ids WHERE external_id = '880301'"),
        )
    ).scalar_one()
    title = (
        await db.execute(text("SELECT title FROM movies WHERE id = :id"), {"id": linked})
    ).scalar_one()
    assert title == "Incremental Movie 880301"


async def test_the_promotion_sweep_only_covers_the_recent_years(db, monkeypatch):
    """The sweep is bounded: the full enumeration stays the tool for the deep catalog."""
    monkeypatch.setattr(settings, "TMDB_PROMOTION_YEARS", 3)
    monkeypatch.setattr(settings, "TMDB_SEED_END_YEAR", None)

    years: list[str] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        years.append(kwargs["params"]["primary_release_date.gte"])
        return _json_response({"page": 1, "total_pages": 1, "total_results": 0, "results": []})

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_promotion(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    this_year = datetime.now(UTC).year
    assert result["end_year"] == this_year + 1
    assert result["start_year"] == this_year - 1
    assert len(years) == 3


# ── 5. Watermarks and lane isolation ──────────────────────────────────────────


async def test_the_first_run_records_a_baseline_instead_of_flooding(db, monkeypatch):
    """With no previous file there is no "appeared" side to the diff.

    Admitting everything the catalog does not have would mean the entire long
    tail TMDB holds and the threshold rejected on purpose — hundreds of
    thousands of ids, none of them a novelty.
    """
    called = {"n": 0}

    def _never(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("the baseline file must not be downloaded on a cold start")

    monkeypatch.setattr(sync_jobs, "load_export_ids", _never, raising=True)

    with patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)):
        result = await sync_jobs._incremental_new_releases(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert called["n"] == 0
    assert result["rebaselined"] is True
    assert result["rebaseline_reason"] == "cold_start"
    assert result["appeared"] == 0

    watermark = await get_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == exports.latest_export_date(datetime.now(UTC)).isoformat()


async def test_a_baseline_too_far_behind_is_rebaselined_and_reported(db, monkeypatch):
    """A month-old baseline is not diffed silently, and it is not diffed at all."""
    monkeypatch.setattr(settings, "TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS", 7)
    monkeypatch.setattr(
        sync_jobs,
        "load_export_ids",
        lambda name, day: (_ for _ in ()).throw(AssertionError("must not download")),
        raising=True,
    )
    today = datetime.now(UTC).date()
    await set_sync_watermark(
        db,
        _SOURCE,
        "DAILY_ID_EXPORT",
        "MOVIE",
        cursor_value=(today - timedelta(days=30)).isoformat(),
    )
    await db.commit()

    with patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)):
        result = await sync_jobs._incremental_new_releases(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["rebaselined"] is True
    assert result["rebaseline_reason"] == "gap_too_large"
    assert result["skipped_days"] >= 29


async def test_a_baseline_no_longer_published_is_rebaselined(db, monkeypatch):
    """TMDB keeps three months of exports; past that there is nothing to diff against."""

    def _gone(name, day):
        raise exports.ExportUnavailable("410")

    monkeypatch.setattr(sync_jobs, "load_export_ids", _gone, raising=True)
    today = datetime.now(UTC).date()
    await set_sync_watermark(
        db,
        _SOURCE,
        "DAILY_ID_EXPORT",
        "MOVIE",
        cursor_value=(today - timedelta(days=2)).isoformat(),
    )
    await db.commit()

    with patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)):
        result = await sync_jobs._incremental_new_releases(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["rebaseline_reason"] == "baseline_unavailable"
    watermark = await get_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == exports.latest_export_date(datetime.now(UTC)).isoformat()


async def test_a_fetch_failure_keeps_the_export_watermark_where_it_was(db, monkeypatch):
    """The mark only advances when the stretch really was covered."""
    today = datetime.now(UTC).date()
    baseline = (today - timedelta(days=1)).isoformat()
    monkeypatch.setattr(sync_jobs, "load_export_ids", lambda name, day: set(), raising=True)
    monkeypatch.setattr(
        sync_jobs,
        "collect_appeared_entries",
        lambda name, day, *, baseline_ids, known_ids: [
            exports.ExportEntry("880401", "Unreachable", 1.0, False, False)
        ],
        raising=True,
    )
    await set_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "MOVIE", cursor_value=baseline)
    await db.commit()

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("TMDB is down")

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        result = await sync_jobs._incremental_new_releases(
            sync_jobs._movie_incremental_spec(), now=datetime.now(UTC)
        )

    assert result["errors"] == 1
    assert result["watermark_advanced"] is False
    watermark = await get_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "MOVIE")
    assert watermark is not None
    assert watermark.cursor_value == baseline


async def test_a_failing_lane_does_not_abort_the_other_two(db, monkeypatch):
    """Checkpoint C19, restated for the three incremental lanes."""

    async def _boom(spec, *, now):
        raise RuntimeError("the export host is unreachable")

    monkeypatch.setattr(sync_jobs, "_incremental_new_releases", _boom, raising=True)
    # ``TMDB_PROMOTION_YEARS`` is the number of ``/discover`` windows the sweep
    # runs (see ``test_the_promotion_sweep_only_covers_the_recent_years``): two
    # here, so "the promotion lane really ran" is a count and not a truthiness.
    monkeypatch.setattr(settings, "TMDB_PROMOTION_YEARS", 2)

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        if "/changes" in url:
            return _json_response({"page": 1, "total_pages": 1, "results": []})
        return _json_response({"page": 1, "total_pages": 1, "total_results": 0, "results": []})

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        summary = await sync_jobs.sync_movies_incremental()

    assert summary["new_releases"] == {"failed": True}
    assert summary["errors"] >= 1
    assert summary["promotion"]["windows"] == 2
    assert summary["changes"]["windows_planned"] == 1
    assert summary["changes"]["covered_through"] == datetime.now(UTC).date().isoformat()


async def test_the_series_incremental_runs_the_same_lanes_on_the_tv_endpoints(db, monkeypatch):
    """The series job is the movie job with a different spec — check the wiring.

    ``_series_incremental_spec`` is the only place where the two content types
    diverge (``tv_series_ids``, ``/tv/changes``, ``/discover/tv`` and
    ``first_air_date`` instead of ``release_date``), so a spec built wrong
    would go unnoticed by every movie test in this file while shipping a
    series lane that queries the wrong endpoint with the wrong date field.
    """
    monkeypatch.setattr(settings, "TMDB_PROMOTION_YEARS", 1)
    calls: list[tuple[str, dict]] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        calls.append((url, kwargs.get("params") or {}))
        if "/changes" in url:
            return _json_response({"page": 1, "total_pages": 1, "results": []})
        return _json_response({"page": 1, "total_pages": 1, "total_results": 0, "results": []})

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_mocked_session_factory(db)),
    ):
        summary = await sync_jobs.sync_series_incremental()

    assert summary["item_type"] == "SERIES"
    assert summary["errors"] == 0
    # Lane 1 has no watermark for SERIES yet, so it records the baseline and
    # downloads nothing — the movie watermarks written by other tests must not
    # be able to stand in for it.
    assert summary["new_releases"]["rebaseline_reason"] == "cold_start"
    watermark = await get_sync_watermark(db, _SOURCE, "DAILY_ID_EXPORT", "SERIES")
    assert watermark is not None

    discover = [params for url, params in calls if "/discover/tv" in url]
    assert len(discover) == 1
    assert "first_air_date.gte" in discover[0]
    assert discover[0]["vote_count.gte"] == settings.TMDB_SEED_MIN_VOTES_SERIES

    changes = [url for url, _ in calls if "/tv/changes" in url]
    assert changes and not [url for url, _ in calls if "/movie/changes" in url]
    assert summary["changes"]["covered_through"] == datetime.now(UTC).date().isoformat()
