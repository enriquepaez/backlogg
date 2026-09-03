"""Tests for feature 86 — tmdb_discover_quality_seeding.

Four things are under test, matching the feature's acceptance list:

1. **The ``/discover`` query built per year window** — threshold, date field
   and the two movie-only flags (``include_adult``/``include_video``).
2. **The 500-page guard** — a year over the cap is split into its twelve
   months, and a month that is *still* over the cap is truncated and reported
   instead of aborting the run.
3. **Single-request hydration** — ``append_to_response=credits,external_ids``
   means the separate ``/{id}/credits`` call is never issued, verified by
   counting the HTTP requests a whole slice makes.
4. **The persisted target list** — the work list is the difference against
   ``external_ids`` (not an offset), the refresh rotation fills the rest of
   the slice by oldest ``last_synced_at``, and re-enumerating is idempotent.
5. **Convergence** — a target that can never link (404 at TMDB, or an id
   another item type already claimed) is *retired* rather than retried
   forever, so ``pending`` reaches 0, the refresh rotation actually fires and
   the backfill loop can terminate.  This is the review's B1.

The database-backed tests run against the real test database; the TMDB layer
is always mocked, so no test touches the network.
"""

import asyncio
import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.models import Movie
from backlogg.scheduler import discovery
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import (
    SeedTargetRow,
    count_seed_target_progress,
    count_seed_targets,
    get_pending_seed_targets,
    get_stale_catalog_external_ids,
    mark_seed_targets_attempted,
    mark_seed_targets_unreachable,
    upsert_seed_targets,
)
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.shared.external_ids import upsert_external_id

# How many conclusive passes a target gets before retirement. Mirrors the
# production default; the tests that exercise retirement set it explicitly.
_MAX_ATTEMPTS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────


def _json_response(payload: dict) -> MagicMock:
    """Minimal stand-in for a 200 httpx.Response."""
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock()
    return response


def _discover_payload(total_pages: int = 1, results: list[dict] | None = None) -> dict:
    return {
        "page": 1,
        "total_pages": total_pages,
        "total_results": len(results or []),
        "results": results if results is not None else [],
    }


def _movie_detail(tmdb_id: int, **overrides) -> dict:
    """A TMDB movie detail payload with credits + external_ids appended."""
    detail = {
        "id": tmdb_id,
        "title": f"Discover Movie {tmdb_id}",
        "original_title": f"Discover Movie {tmdb_id}",
        "overview": "Seeded through /discover.",
        "release_date": "2019-06-01",
        "runtime": 101,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.4,
        "vote_count": 1200,
        "genres": [],
        "credits": {
            "cast": [{"id": 900_001, "name": "Discover Actor", "character": "Lead", "order": 0}],
            "crew": [{"id": 900_002, "name": "Discover Director", "job": "Director"}],
        },
        "external_ids": {"imdb_id": f"tt{tmdb_id}"},
    }
    detail.update(overrides)
    return detail


def _mocked_session_factory(session):
    """Session factory whose context manager yields ``session``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


# ── 1. The /discover query per year window ────────────────────────────────────


async def test_discover_movies_page_builds_the_year_query():
    """Movies: vote_count.gte, a closed primary_release_date window and both flags."""
    client = TMDBClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_json_response(_discover_payload()),
    ) as mock_get:
        await client.discover_movies_page(
            page=3,
            min_votes=25,
            date_gte=date(2019, 1, 1),
            date_lte=date(2019, 12, 31),
        )

    url = mock_get.call_args.args[0]
    assert url.endswith("/discover/movie")
    assert mock_get.call_args.kwargs["params"] == {
        "page": 3,
        "include_adult": "false",
        "include_video": "false",
        "sort_by": "primary_release_date.asc",
        "vote_count.gte": 25,
        "primary_release_date.gte": "2019-01-01",
        "primary_release_date.lte": "2019-12-31",
    }


async def test_discover_series_page_uses_first_air_date():
    """Series: the date field is first_air_date, not primary_release_date."""
    client = TMDBSeriesClient()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_json_response(_discover_payload()),
    ) as mock_get:
        await client.discover_series_page(
            page=1,
            min_votes=25,
            date_gte=date(2022, 1, 1),
            date_lte=date(2022, 12, 31),
        )

    params = mock_get.call_args.kwargs["params"]
    assert mock_get.call_args.args[0].endswith("/discover/tv")
    assert params["vote_count.gte"] == 25
    assert params["first_air_date.gte"] == "2022-01-01"
    assert params["first_air_date.lte"] == "2022-12-31"
    assert "primary_release_date.gte" not in params
    # /discover/tv has no include_video counterpart.
    assert "include_video" not in params


def test_year_windows_are_closed_calendar_years_oldest_first():
    windows = discovery.year_windows(2018, 2020)
    assert [w.label for w in windows] == ["2018", "2019", "2020"]
    assert windows[0].start == date(2018, 1, 1)
    assert windows[0].end == date(2018, 12, 31)
    assert all(w.splittable for w in windows)


def test_year_windows_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="before start_year"):
        discovery.year_windows(2020, 2019)


def test_month_windows_cover_the_year_without_gaps_or_overlaps():
    """Twelve closed windows, February included, ending on 31 December."""
    windows = discovery.month_windows(2024)  # a leap year
    assert len(windows) == 12
    assert windows[1].start == date(2024, 2, 1)
    assert windows[1].end == date(2024, 2, 29)
    assert windows[-1].end == date(2024, 12, 31)
    assert not any(w.splittable for w in windows)
    for previous, following in zip(windows, windows[1:], strict=False):
        assert following.start == previous.end + timedelta(days=1)


async def test_enumeration_maps_results_and_streams_them_to_the_sink():
    """Ids, vote counts and release years come back mapped; the sink sees pages."""
    payloads = {
        1: _discover_payload(
            total_pages=2,
            results=[{"id": 11, "vote_count": 90, "release_date": "2019-03-02"}],
        ),
        2: _discover_payload(
            total_pages=2,
            results=[{"id": 12, "vote_count": 30, "release_date": ""}, {"id": None}],
        ),
    }

    async def fetch_page(*, page, date_gte, date_lte):  # noqa: ARG001
        return payloads[page]

    collected: list[discovery.DiscoveredTarget] = []

    async def sink(targets):
        collected.extend(targets)

    stats = await discovery.enumerate_windows(
        discovery.year_windows(2019, 2019),
        fetch_page=fetch_page,
        date_key="release_date",
        on_targets=sink,
        concurrency=4,
    )

    assert stats.windows == 1
    assert stats.pages == 2
    assert stats.targets == 2  # the id-less row is dropped
    assert [t.external_id for t in collected] == ["11", "12"]
    assert collected[0].release_year == 2019
    assert collected[0].vote_count == 90
    assert collected[1].release_year is None  # missing date costs the year, not the target


# ── 2. The 500-page guard ─────────────────────────────────────────────────────


def test_page_cap_is_tmdbs_documented_500():
    """The guard's constant must stay pinned to TMDB's real cap."""
    assert discovery.MAX_DISCOVER_PAGES == 500


async def test_year_over_the_page_cap_is_split_into_months(monkeypatch):
    """A year declaring more pages than the cap is re-enumerated month by month."""
    # Lower the cap instead of faking 500 pages: same code path, fast test.
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    requested: list[tuple[date, date, int]] = []

    async def fetch_page(*, page, date_gte, date_lte):
        requested.append((date_gte, date_lte, page))
        if (date_gte, date_lte) == (date(2019, 1, 1), date(2019, 12, 31)):
            return _discover_payload(total_pages=3)  # over the cap
        return _discover_payload(total_pages=1, results=[{"id": date_gte.month}])

    collected: list[discovery.DiscoveredTarget] = []

    async def sink(targets):
        collected.extend(targets)

    stats = await discovery.enumerate_windows(
        discovery.year_windows(2019, 2019),
        fetch_page=fetch_page,
        date_key="release_date",
        on_targets=sink,
        concurrency=4,
    )

    assert stats.split_windows == 1
    assert stats.truncated_windows == 0
    assert stats.windows == 12  # the twelve months, not the year
    # The year's own page 1 is fetched once — that is how the cap is detected —
    # and then each of the twelve months is enumerated on its own.
    assert requested[0] == (date(2019, 1, 1), date(2019, 12, 31), 1)
    month_requests = requested[1:]
    assert len(month_requests) == 12
    assert month_requests[1] == (date(2019, 2, 1), date(2019, 2, 28), 1)
    assert month_requests[-1] == (date(2019, 12, 1), date(2019, 12, 31), 1)
    assert len(collected) == 12


async def test_month_still_over_the_cap_is_truncated_and_reported(monkeypatch):
    """A window that cannot be split further is capped, not aborted — and flagged."""
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)
    pages_fetched: list[int] = []

    async def fetch_page(*, page, date_gte, date_lte):  # noqa: ARG001
        pages_fetched.append(page)
        return _discover_payload(total_pages=5, results=[{"id": 1000 + page}])

    collected: list[discovery.DiscoveredTarget] = []

    async def sink(targets):
        collected.extend(targets)

    window = discovery.DateWindow(
        label="2019-01", start=date(2019, 1, 1), end=date(2019, 1, 31), splittable=False
    )
    stats = await discovery.enumerate_windows(
        [window],
        fetch_page=fetch_page,
        date_key="release_date",
        on_targets=sink,
        concurrency=4,
    )

    assert stats.truncated_windows == 1
    assert stats.truncated_labels == ["2019-01"]
    assert sorted(pages_fetched) == [1, 2]  # capped, not 5
    assert stats.pages == 2
    assert len(collected) == 2


async def test_window_within_the_cap_is_not_split(monkeypatch):
    """The guard is a guard: a normal year is enumerated as one window."""
    monkeypatch.setattr(discovery, "MAX_DISCOVER_PAGES", 2)

    async def fetch_page(*, page, date_gte, date_lte):  # noqa: ARG001
        return _discover_payload(total_pages=2, results=[{"id": page}])

    async def sink(targets):
        return None

    stats = await discovery.enumerate_windows(
        discovery.year_windows(2019, 2019),
        fetch_page=fetch_page,
        date_key="release_date",
        on_targets=sink,
        concurrency=4,
    )
    assert stats.split_windows == 0
    assert stats.truncated_windows == 0
    assert stats.windows == 1


# ── 3. Single-request hydration ───────────────────────────────────────────────


async def test_movie_hydration_issues_one_request_with_append_to_response():
    """The credits call is folded into the detail call — one request, both payloads."""
    requested: list[str] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        requested.append(url)
        assert kwargs["params"] == {"append_to_response": "credits,external_ids"}
        return _json_response(_movie_detail(550))

    with patch("httpx.AsyncClient.get", new=fake_get):
        data, people = await sync_jobs._fetch_movie_payload("550")

    assert len(requested) == 1
    assert requested[0].endswith("/movie/550")
    assert not any(url.endswith("/credits") for url in requested)
    assert data["title"] == "Discover Movie 550"
    assert [person.role for person in people] == ["ACTOR", "DIRECTOR"]


async def test_series_hydration_issues_one_request_with_cast_and_creators():
    """Series get cast *and* created_by from the same single request."""
    requested: list[str] = []
    detail = {
        "id": 1399,
        "name": "Discover Series",
        "original_name": "Discover Series",
        "overview": "",
        "first_air_date": "2011-04-17",
        "last_air_date": "2019-05-19",
        "number_of_seasons": 8,
        "number_of_episodes": 73,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 8.4,
        "vote_count": 20000,
        "genres": [],
        "created_by": [{"id": 900_003, "name": "Discover Creator", "profile_path": None}],
        "credits": {
            "cast": [{"id": 900_004, "name": "Discover Star", "character": "Hero", "order": 0}]
        },
        "external_ids": {"imdb_id": "tt0944947"},
    }

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        requested.append(url)
        assert kwargs["params"] == {"append_to_response": "credits,external_ids"}
        return _json_response(detail)

    with patch("httpx.AsyncClient.get", new=fake_get):
        data, people = await sync_jobs._fetch_series_payload("1399")

    assert len(requested) == 1
    assert not any(url.endswith("/credits") for url in requested)
    assert data["title"] == "Discover Series"
    assert sorted(person.role for person in people) == ["ACTOR", "CREATOR"]


async def test_sync_movies_slice_never_calls_the_credits_endpoint(db):
    """End to end: a whole slice issues exactly one HTTP request per item."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "860001", vote_count=500, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "860002", vote_count=400, release_year=2019),
        ],
    )
    await db.commit()

    requested: list[str] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        requested.append(url)
        tmdb_id = int(url.rsplit("/", 1)[-1])
        return _json_response(_movie_detail(tmdb_id))

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=10)

    assert result["synced"] == 2
    assert result["errors"] == 0
    assert len(requested) == 2, f"expected 1 request per item, got {requested}"
    assert not any("/credits" in url for url in requested)
    assert result["pending"] == 0


# ── 4. The persisted target list ──────────────────────────────────────────────


async def test_upsert_seed_targets_is_idempotent_and_keeps_attempts(db):
    """Re-enumerating refreshes the observed values without resetting progress."""
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "861001", vote_count=30, release_year=2001)]
    )
    await mark_seed_targets_attempted(db, "MOVIE", "TMDB", ["861001"], datetime.now(UTC))
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "861001", vote_count=44, release_year=2001)]
    )
    await db.flush()

    assert await count_seed_targets(db, "MOVIE", "TMDB") == 1
    row = (
        await db.execute(
            text("SELECT vote_count, attempts FROM seed_targets WHERE external_id = '861001'")
        )
    ).one()
    assert row.vote_count == 44
    assert row.attempts == 1


async def test_upsert_seed_targets_deduplicates_within_one_payload(db):
    """The same id twice in one page must not blow up ON CONFLICT."""
    written = await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "861010", vote_count=10, release_year=2000),
            SeedTargetRow("MOVIE", "TMDB", "861010", vote_count=20, release_year=2000),
        ],
    )
    assert written == 1
    assert await count_seed_targets(db, "MOVIE", "TMDB") == 1


async def test_pending_targets_are_the_difference_against_the_catalog(db):
    """A target already linked in external_ids drops out of the work list."""
    movie = Movie(
        title="Already Seeded",
        slug="already-seeded-2019-86",
        last_synced_at=datetime.now(UTC),
    )
    db.add(movie)
    await db.flush()
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "862001")
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "862001", vote_count=900, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "862002", vote_count=800, release_year=2019),
        ],
    )
    await db.flush()

    assert await count_seed_targets(db, "MOVIE", "TMDB") == 2
    assert (await count_seed_target_progress(db, "MOVIE", "TMDB", _MAX_ATTEMPTS)).pending == 1
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == ["862002"]


async def test_pending_targets_are_ordered_by_attempts_then_notoriety(db):
    """Never-tried targets first; within a tier, the most voted first."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "863001", vote_count=5000, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "863002", vote_count=100, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "863003", vote_count=900, release_year=2019),
        ],
    )
    await db.flush()
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == [
        "863001",
        "863003",
        "863002",
    ]

    # A target that could not be linked drifts behind the untried ones instead
    # of camping at the head of the queue forever.
    await mark_seed_targets_attempted(db, "MOVIE", "TMDB", ["863001"], datetime.now(UTC))
    await db.flush()
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == [
        "863003",
        "863002",
        "863001",
    ]


async def test_pending_targets_do_not_leak_across_item_types(db):
    """The same TMDB id can be a movie target and a series target."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "864001", vote_count=10, release_year=2019),
            SeedTargetRow("SERIES", "TMDB", "864001", vote_count=10, release_year=2019),
        ],
    )
    await db.flush()
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == ["864001"]
    assert await get_pending_seed_targets(db, "SERIES", "TMDB", 10, _MAX_ATTEMPTS) == ["864001"]


async def test_refresh_rotation_returns_the_least_recently_synced_items(db):
    """The 6-month cache window is kept by rotating on last_synced_at."""
    now = datetime.now(UTC)
    for index, age_days in enumerate((400, 1, 200)):
        movie = Movie(
            title=f"Rotation {index}",
            slug=f"rotation-{index}-86",
            last_synced_at=now - timedelta(days=age_days),
        )
        db.add(movie)
        await db.flush()
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", f"86500{index}")
    await db.flush()

    assert await get_stale_catalog_external_ids(db, "MOVIE", "TMDB", 2) == ["865000", "865002"]
    assert await get_stale_catalog_external_ids(db, "MOVIE", "TMDB", 0) == []


async def test_sync_movies_fills_the_slice_with_pending_then_rotation(db):
    """One pending target plus one rotation item make up a slice of two."""
    now = datetime.now(UTC)
    stale = Movie(
        title="Stale Movie", slug="stale-movie-86", last_synced_at=now - timedelta(days=400)
    )
    fresh = Movie(title="Fresh Movie", slug="fresh-movie-86", last_synced_at=now)
    db.add_all([stale, fresh])
    await db.flush()
    await upsert_external_id(db, "MOVIE", stale.id, "TMDB", "866001")
    await upsert_external_id(db, "MOVIE", fresh.id, "TMDB", "866002")
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "866003", vote_count=700, release_year=2019)]
    )
    await db.commit()

    requested: list[int] = []

    async def fake_get(self, url, **kwargs):  # noqa: ARG001
        tmdb_id = int(url.rsplit("/", 1)[-1])
        requested.append(tmdb_id)
        return _json_response(_movie_detail(tmdb_id))

    with (
        patch("httpx.AsyncClient.get", new=fake_get),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=2)

    # The pending target first, then the oldest catalog item — never the fresh one.
    assert requested == [866003, 866001]
    assert result["refreshed"] == 1
    assert result["pending"] == 0
    assert result["offset"] == 0


async def test_sync_movies_reads_no_sync_cursor(db):
    """sync_cursors is out of the movie path entirely (no offset to resume from)."""
    with (
        patch("backlogg.scheduler.jobs.get_sync_offset", new_callable=AsyncMock) as get_cursor,
        patch("backlogg.scheduler.jobs.set_sync_offset", new_callable=AsyncMock) as set_cursor,
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=5)

    get_cursor.assert_not_awaited()
    set_cursor.assert_not_awaited()
    assert result["synced"] == 0
    assert result["errors"] == 0


async def test_sync_movies_counts_a_fetch_failure_without_losing_the_slice(db):
    """One item failing costs one error; the rest of the slice still lands."""
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "867001", vote_count=900, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "867002", vote_count=800, release_year=2019),
        ],
    )
    await db.commit()

    async def flaky_detail(tmdb_id, append_to_response=None):  # noqa: ARG001
        if tmdb_id == 867001:
            raise RuntimeError("TMDB is down for this one")
        return _movie_detail(tmdb_id)

    with (
        patch.object(sync_jobs._tmdb_movies, "get_movie_detail", new=flaky_detail),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=10)

    assert result["synced"] == 1
    assert result["errors"] == 1
    # The failed target keeps no external_ids row, so it stays pending.
    assert result["pending"] == 1


async def test_sync_movies_retires_an_id_tmdb_no_longer_serves(db):
    """A 404 is not an error, and it is *definitive*: the target is retired now.

    Re-asking would spend a slice slot and a TMDB request every run for an
    answer that will not change, and would hold ``pending`` above 0 forever —
    which is exactly what would stop the refresh rotation from ever firing.
    """
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "868001", vote_count=900, release_year=2019)]
    )
    await db.commit()

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=10)

    assert result["synced"] == 0
    assert result["errors"] == 0
    # Retired on the first observation: out of pending, visible in stuck.
    assert result["pending"] == 0
    assert result["stuck"] == 1
    row = (
        await db.execute(
            text("SELECT attempts, unreachable_at FROM seed_targets WHERE external_id = '868001'")
        )
    ).one()
    assert row.unreachable_at is not None
    assert row.attempts == 0  # a 404 is a verdict, not a "pass"
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == []


async def test_sync_series_is_target_driven_too(db):
    """The series job shares the whole mechanism, with its own item type."""
    await upsert_seed_targets(
        db, [SeedTargetRow("SERIES", "TMDB", "869001", vote_count=600, release_year=2022)]
    )
    await db.commit()

    detail = {
        "id": 869001,
        "name": "Target Driven Series",
        "original_name": "Target Driven Series",
        "overview": "",
        "first_air_date": "2022-01-05",
        "last_air_date": "2022-03-05",
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.9,
        "vote_count": 600,
        "genres": [],
        "created_by": [],
        "credits": {"cast": []},
    }

    with (
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ) as mock_detail,
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_series(slice_size=5)

    mock_detail.assert_awaited_once_with(869001, append_to_response="credits,external_ids")
    assert result["synced"] == 1
    assert result["pending"] == 0


# ── 5. The enumeration CLI ────────────────────────────────────────────────────
#
# ``scripts/`` is not an installed package, so the script is loaded by path —
# the same trick ``tests/test_backfill_sync.py`` uses.

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "seed_tmdb_targets.py"
_spec = importlib.util.spec_from_file_location("seed_tmdb_targets", _SCRIPT_PATH)
seed_script = importlib.util.module_from_spec(_spec)
sys.modules["seed_tmdb_targets"] = seed_script
_spec.loader.exec_module(seed_script)


def test_seed_cli_rejects_an_unknown_content_type():
    """Only movie and series are enumerable this way."""
    with pytest.raises(SystemExit) as excinfo:
        seed_script.main(["book"])
    assert excinfo.value.code != 0


def test_seed_cli_defaults_the_threshold_to_the_per_type_setting(monkeypatch):
    """No --min-votes means TMDB_SEED_MIN_VOTES_<TYPE>, not a hardcoded 25."""
    monkeypatch.setattr(seed_script.settings, "TMDB_SEED_MIN_VOTES_SERIES", 77)
    summary = {
        "content_type": "series",
        "windows": 1,
        "split_windows": 0,
        "truncated_windows": 0,
        "truncated_labels": [],
        "pages": 1,
        "enumerated": 3,
        "targets_total": 3,
        "targets_pending": 3,
        "targets_stuck": 0,
    }
    with (
        patch.object(
            seed_script, "run_enumeration", new_callable=AsyncMock, return_value=summary
        ) as mock_run,
        patch.object(seed_script, "engine", new=AsyncMock()),
    ):
        code = seed_script.main(["series", "--start-year", "2020", "--end-year", "2021"])

    assert code == 0
    mock_run.assert_awaited_once_with(
        "series", 77, 2020, 2021, seed_script.settings.TMDB_SEED_CONCURRENCY
    )


def test_seed_cli_forwards_an_explicit_threshold():
    summary = {
        "content_type": "movie",
        "windows": 1,
        "split_windows": 0,
        "truncated_windows": 0,
        "truncated_labels": [],
        "pages": 1,
        "enumerated": 0,
        "targets_total": 0,
        "targets_pending": 0,
        "targets_stuck": 0,
    }
    with (
        patch.object(
            seed_script, "run_enumeration", new_callable=AsyncMock, return_value=summary
        ) as mock_run,
        patch.object(seed_script, "engine", new=AsyncMock()),
    ):
        code = seed_script.main(
            [
                "movie",
                "--min-votes",
                "50",
                "--start-year",
                "2019",
                "--end-year",
                "2019",
                "--concurrency",
                "3",
            ]
        )

    assert code == 0
    mock_run.assert_awaited_once_with("movie", 50, 2019, 2019, 3)


def test_seed_cli_exits_non_zero_when_a_window_was_truncated():
    """An incomplete enumeration must not be reported as a green run."""
    summary = {
        "content_type": "movie",
        "windows": 12,
        "split_windows": 1,
        "truncated_windows": 1,
        "truncated_labels": ["2019-06"],
        "pages": 500,
        "enumerated": 10000,
        "targets_total": 10000,
        "targets_pending": 10000,
        "targets_stuck": 0,
    }
    with (
        patch.object(seed_script, "run_enumeration", new_callable=AsyncMock, return_value=summary),
        patch.object(seed_script, "engine", new=AsyncMock()),
    ):
        code = seed_script.main(["movie"])

    assert code == 2


def test_seed_cli_returns_one_on_an_unrecoverable_failure():
    with (
        patch.object(
            seed_script,
            "run_enumeration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TMDB is down"),
        ),
        patch.object(seed_script, "engine", new=AsyncMock()),
    ):
        code = seed_script.main(["movie"])

    assert code == 1


def test_seed_cli_end_year_defaults_to_next_year(monkeypatch):
    monkeypatch.setattr(seed_script.settings, "TMDB_SEED_END_YEAR", None)
    assert seed_script._resolve_end_year(None) == datetime.now(UTC).year + 1
    assert seed_script._resolve_end_year(2001) == 2001
    monkeypatch.setattr(seed_script.settings, "TMDB_SEED_END_YEAR", 2030)
    assert seed_script._resolve_end_year(None) == 2030


async def test_run_enumeration_persists_the_targets_it_finds(db):
    """End to end against the real database: /discover results land in seed_targets."""
    payload = _discover_payload(
        total_pages=1,
        results=[
            {"id": 870001, "vote_count": 300, "release_date": "2019-04-01"},
            {"id": 870002, "vote_count": 40, "release_date": "2019-08-11"},
        ],
    )

    with (
        patch.object(
            seed_script,
            "async_session_factory",
            new=_mocked_session_factory(db),
        ),
        patch(
            "backlogg.movies.adapters.tmdb.TMDBClient.discover_movies_page",
            new_callable=AsyncMock,
            return_value=payload,
        ) as mock_page,
    ):
        summary = await seed_script.run_enumeration("movie", 25, 2019, 2019, concurrency=4)

    mock_page.assert_awaited_once()
    assert mock_page.await_args.kwargs["min_votes"] == 25
    assert mock_page.await_args.kwargs["date_gte"] == date(2019, 1, 1)
    assert summary["enumerated"] == 2
    assert summary["targets_total"] == 2
    assert summary["targets_pending"] == 2
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, _MAX_ATTEMPTS) == [
        "870001",
        "870002",
    ]


# ── 6. Convergence: retirement of targets that can never link (review B1) ─────
#
# Two unrelated causes put a target permanently out of reach:
#
# * TMDB answers 404 for an enumerated id (covered above by
#   ``test_sync_movies_retires_an_id_tmdb_no_longer_serves``);
# * ``uq_external_id`` is unique over ``(source, external_id)`` *globally* while
#   TMDB numbers movies and series in independent sequences, so a series can
#   find its id already claimed by a movie: the row is written, the link never
#   happens.
#
# Both used to hold ``pending`` permanently above 0, which silently disabled the
# ``last_synced_at`` refresh rotation — and with it TMDB's 6-month cache-window
# obligation — and stopped ``scripts/backfill_sync.py`` from ever terminating.


async def _claim_tmdb_id_for_a_movie(db, tmdb_id: str) -> None:
    """Make ``tmdb_id`` unlinkable for any other item type, the way prod does."""
    movie = Movie(
        title=f"Claimer {tmdb_id}",
        slug=f"claimer-{tmdb_id}-86",
        last_synced_at=datetime.now(UTC),
    )
    db.add(movie)
    await db.flush()
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", tmdb_id)


async def test_unlinkable_target_is_retired_so_pending_reaches_zero(db, monkeypatch):
    """A target that resolves but never links leaves the work list after N passes.

    Regression for review B1: ordering by ``attempts`` alone reordered the
    queue without removing anything, so this target kept a slice slot and kept
    ``pending`` at 1 on every single run, forever.
    """
    monkeypatch.setattr(sync_jobs.settings, "TMDB_SEED_MAX_ATTEMPTS", 2)
    await _claim_tmdb_id_for_a_movie(db, "871001")
    await upsert_seed_targets(
        db, [SeedTargetRow("SERIES", "TMDB", "871001", vote_count=500, release_year=2022)]
    )
    await db.commit()

    detail = {
        "id": 871001,
        "name": "Unlinkable Series",
        "original_name": "Unlinkable Series",
        "overview": "",
        "first_air_date": "2022-01-05",
        "last_air_date": "2022-03-05",
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.9,
        "vote_count": 500,
        "genres": [],
        "created_by": [],
        "credits": {"cast": []},
    }

    results = []
    with (
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        for _ in range(3):
            results.append(await sync_jobs.sync_series(slice_size=1))

    # Pass 1 and 2 are conclusive-but-unlinked; the target retires on the 2nd.
    assert [r["pending"] for r in results] == [1, 0, 0]
    assert [r["stuck"] for r in results] == [0, 1, 1]
    # And it is really out of the work list, not merely at the back of it.
    assert await get_pending_seed_targets(db, "SERIES", "TMDB", 10, 2) == []


async def test_a_failed_fetch_does_not_burn_a_targets_budget(db, monkeypatch):
    """A TMDB outage must never retire a healthy target.

    Only *conclusive* passes count, so three consecutive network failures leave
    ``attempts`` at 0 and the target fully workable.
    """
    monkeypatch.setattr(sync_jobs.settings, "TMDB_SEED_MAX_ATTEMPTS", 2)
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "872001", vote_count=500, release_year=2019)]
    )
    await db.commit()

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            side_effect=RuntimeError("TMDB is down"),
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        for _ in range(3):
            result = await sync_jobs.sync_movies(slice_size=1)

    assert result["errors"] == 1
    assert result["pending"] == 1  # still workable
    assert result["stuck"] == 0
    row = (
        await db.execute(text("SELECT attempts FROM seed_targets WHERE external_id = '872001'"))
    ).one()
    assert row.attempts == 0


async def test_refresh_rotation_fires_once_the_stuck_target_is_retired(db, monkeypatch):
    """The point of B1: with the residue retired, the rotation actually runs.

    Before the fix the stuck target occupied the whole slice on every run and
    the stale catalog item — the one TMDB's 6-month cache window obliges us to
    re-sync — was never visited.
    """
    monkeypatch.setattr(sync_jobs.settings, "TMDB_SEED_MAX_ATTEMPTS", 1)
    await _claim_tmdb_id_for_a_movie(db, "873001")
    stale = Movie(
        title="Stale Rotation Movie",
        slug="stale-rotation-movie-86",
        last_synced_at=datetime.now(UTC) - timedelta(days=400),
    )
    db.add(stale)
    await db.flush()
    await upsert_external_id(db, "MOVIE", stale.id, "TMDB", "873002")
    await upsert_seed_targets(
        db, [SeedTargetRow("SERIES", "TMDB", "873001", vote_count=500, release_year=2022)]
    )
    await db.commit()

    series_detail = {
        "id": 873001,
        "name": "Stuck Series",
        "original_name": "Stuck Series",
        "overview": "",
        "first_air_date": "2022-01-05",
        "last_air_date": "2022-03-05",
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.9,
        "vote_count": 500,
        "genres": [],
        "created_by": [],
        "credits": {"cast": []},
    }
    # A series row whose external id is claimed by the movie above: it is
    # written, never linked, and after 1 conclusive pass it is retired.
    with (
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=series_detail,
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        first = await sync_jobs.sync_series(slice_size=1)

    assert first["refreshed"] == 0  # the slice went entirely to the stuck target
    assert first["pending"] == 0
    assert first["stuck"] == 1

    # Now the movie job: nothing pending for MOVIE, so the slice must be the
    # rotation, and it must pick the 400-day-old row.
    requested: list[int] = []

    async def fake_detail(tmdb_id, append_to_response=None):  # noqa: ARG001
        requested.append(tmdb_id)
        return _movie_detail(tmdb_id)

    with (
        patch.object(sync_jobs._tmdb_movies, "get_movie_detail", new=fake_detail),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        second = await sync_jobs.sync_movies(slice_size=1)

    assert requested == [873002]  # the stale one, not the claimer
    assert second["refreshed"] == 1


async def test_seed_failure_reports_unknown_progress_not_zero(db):
    """Review N1: a work-list read that blows up must not claim "nothing left"."""
    with patch(
        "backlogg.scheduler.jobs._read_seed_work_list",
        new_callable=AsyncMock,
        side_effect=RuntimeError("the database is down"),
    ):
        result = await sync_jobs.sync_movies(slice_size=5)

    assert result["errors"] == 1
    assert result["pending"] is None
    assert result["stuck"] is None


async def test_hydration_never_exceeds_the_configured_concurrency(db, monkeypatch):
    """Review N3: the Semaphore really bounds the in-flight TMDB requests."""
    monkeypatch.setattr(sync_jobs.settings, "TMDB_SEED_CONCURRENCY", 3)
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", str(874000 + i), vote_count=500 - i, release_year=2019)
            for i in range(12)
        ],
    )
    await db.commit()

    in_flight = 0
    peak = 0

    async def fake_detail(tmdb_id, append_to_response=None):  # noqa: ARG001
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            # Yield control so every task that *could* run concurrently does.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return _movie_detail(tmdb_id)
        finally:
            in_flight -= 1

    with (
        patch.object(sync_jobs._tmdb_movies, "get_movie_detail", new=fake_detail),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(db),
        ),
    ):
        result = await sync_jobs.sync_movies(slice_size=12)

    assert result["synced"] == 12
    assert peak == 3, f"expected the semaphore to cap in-flight requests at 3, saw {peak}"


async def test_progress_counters_separate_pending_from_gone_and_unlinkable(db):
    """The residue is *visible*, not folded into pending (review B1).

    A catalog that cannot converge because of the pre-existing global
    ``uq_external_id`` is exactly what the operator needs to be able to see, so
    it gets its own counters instead of an unmoving ``pending``.
    """
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "875001", vote_count=900, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "875002", vote_count=800, release_year=2019),
            SeedTargetRow("MOVIE", "TMDB", "875003", vote_count=700, release_year=2019),
        ],
    )
    now = datetime.now(UTC)
    await mark_seed_targets_unreachable(db, "MOVIE", "TMDB", ["875002"], now)
    for _ in range(2):
        await mark_seed_targets_attempted(db, "MOVIE", "TMDB", ["875003"], now)
    await db.flush()

    progress = await count_seed_target_progress(db, "MOVIE", "TMDB", 2)
    assert progress.total == 3
    assert progress.pending == 1  # only 875001 is workable
    assert progress.gone == 1  # 875002, 404 at TMDB
    assert progress.unlinkable == 1  # 875003, out of conclusive passes
    assert progress.stuck == 2
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 2) == ["875001"]

    # Raising the budget puts the unlinkable one back to work; the 404 stays
    # retired, because that answer does not change with more attempts.
    relaxed = await count_seed_target_progress(db, "MOVIE", "TMDB", 5)
    assert relaxed.pending == 2
    assert relaxed.gone == 1
    assert relaxed.unlinkable == 0
