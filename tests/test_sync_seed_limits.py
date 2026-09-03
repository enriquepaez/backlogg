"""Tests for feature 23 — seed_config_wiring.

The cursor-driven jobs (``book`` and ``game``) must read their fetch limit
from ``settings.SEED_TOP_N_*`` at execution time instead of from a hardcoded
value.  We monkeypatch the setting to a value different from the default
(100) and assert that the adapter receives exactly that value.

With the slice-cursor flow (feature 24) the effective limit is
``min(SYNC_SLICE_SIZE, SEED_TOP_N_* - offset)``; the cursor is mocked at 0
and ``SEED_TOP_N_*`` is below the default slice size, so the adapter must
still receive exactly the configured seed value.

⚠️ **Movies and series are no longer covered by this file** (feature 86).
Their catalog stopped being "the first N items of a popularity ranking" and
became "every item over a ``vote_count`` threshold", enumerated into
``seed_targets``; there is no fetch limit for ``SEED_TOP_N_*`` to configure
and the setting is inert for them.  What sizes their slice now is
``SYNC_SLICE_SIZE_<TYPE>``, and that is asserted below and in
``tests/test_tmdb_discover_seeding.py``.

All external API clients are mocked so no real network calls are made, and
``async_session_factory`` / ``_refresh_catalog_search`` / the sync-cursor
repository are mocked so no real DB access happens.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import SeedTargetProgress

_CUSTOM_LIMIT = 7


def _mocked_session_factory():
    """Return a mock session factory whose context manager yields a mock session."""
    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=mock_cm)
    return factory


def _cursor_patches():
    """Patches for the sync-cursor repository: cursor at 0, writes mocked."""
    return (
        patch(
            "backlogg.scheduler.jobs.get_sync_offset",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "backlogg.scheduler.jobs.set_sync_offset",
            new_callable=AsyncMock,
        ),
    )


def _seed_work_list_patch():
    """Patch the seed work-list read, capturing the slice size it is asked for."""
    return patch(
        "backlogg.scheduler.jobs._read_seed_work_list",
        new_callable=AsyncMock,
        return_value=([], [], SeedTargetProgress(total=0, pending=0, gone=0, unlinkable=0)),
    )


async def test_sync_movies_slice_size_comes_from_the_per_type_setting(monkeypatch):
    """Feature 86: SEED_TOP_N_MOVIES is inert; SYNC_SLICE_SIZE_MOVIES sizes the slice."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_MOVIES", 1)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE_MOVIES", _CUSTOM_LIMIT)

    with (
        _seed_work_list_patch() as mock_work_list,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(),
        ),
    ):
        result = await sync_jobs.sync_movies()

    # SEED_TOP_N_MOVIES=1 must not shrink anything — the slice is 7, not 1.
    mock_work_list.assert_awaited_once_with("MOVIE", "TMDB", _CUSTOM_LIMIT)
    assert result["errors"] == 0


async def test_sync_series_slice_size_comes_from_the_per_type_setting(monkeypatch):
    """Same for series: SYNC_SLICE_SIZE_SERIES, not SEED_TOP_N_SERIES."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_SERIES", 1)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE_SERIES", _CUSTOM_LIMIT)

    with (
        _seed_work_list_patch() as mock_work_list,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(),
        ),
    ):
        result = await sync_jobs.sync_series()

    mock_work_list.assert_awaited_once_with("SERIES", "TMDB", _CUSTOM_LIMIT)
    assert result["errors"] == 0


async def test_sync_movies_ignores_seed_top_n(monkeypatch):
    """SEED_TOP_N_MOVIES is documented as inert — prove it changes nothing."""
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE_MOVIES", 25)
    sizes = []

    async def capture(item_type, source, slice_size):
        sizes.append((item_type, source, slice_size))
        return [], [], SeedTargetProgress(total=0, pending=0, gone=0, unlinkable=0)

    for seed_top_n in (1, 10_000):
        monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_MOVIES", seed_top_n)
        with (
            patch("backlogg.scheduler.jobs._read_seed_work_list", new=capture),
            patch(
                "backlogg.scheduler.jobs._refresh_catalog_search",
                new_callable=AsyncMock,
            ),
            patch(
                "backlogg.scheduler.jobs.async_session_factory",
                new=_mocked_session_factory(),
            ),
        ):
            await sync_jobs.sync_movies()

    assert sizes == [("MOVIE", "TMDB", 25), ("MOVIE", "TMDB", 25)]


async def test_sync_books_limit_comes_from_settings(monkeypatch):
    """sync_books passes settings.SEED_TOP_N_BOOKS as limit to the adapter."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", _CUSTOM_LIMIT)
    get_cursor, set_cursor = _cursor_patches()

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_books()

    mock_fetch.assert_awaited_once_with(limit=_CUSTOM_LIMIT, offset=0)
    assert result["errors"] == 0


async def test_sync_games_limit_comes_from_settings(monkeypatch):
    """sync_games passes settings.SEED_TOP_N_GAMES as limit to the adapter."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_GAMES", _CUSTOM_LIMIT)
    get_cursor, set_cursor = _cursor_patches()

    with (
        patch.object(
            sync_jobs._igdb_client,
            "get_top_games",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch,
        patch(
            "backlogg.scheduler.jobs._refresh_catalog_search",
            new_callable=AsyncMock,
        ),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=_mocked_session_factory(),
        ),
        get_cursor,
        set_cursor,
    ):
        result = await sync_jobs.sync_games()

    mock_fetch.assert_awaited_once_with(limit=_CUSTOM_LIMIT, offset=0)
    assert result["errors"] == 0
