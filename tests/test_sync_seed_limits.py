"""Tests for feature 23 — seed_config_wiring.

Each sync job must read its fetch limit from ``settings.SEED_TOP_N_*`` at
execution time instead of a hardcoded value.  We monkeypatch the setting to a
value different from the default (100) and assert that the adapter receives
exactly that value.

With the slice-cursor flow (feature 24) the effective limit is
``min(SYNC_SLICE_SIZE, SEED_TOP_N_* - offset)``; the cursor is mocked at 0
and ``SEED_TOP_N_*`` is below the default slice size, so the adapter must
still receive exactly the configured seed value.

All external API clients are mocked so no real network calls are made, and
``async_session_factory`` / ``_refresh_catalog_search`` / the sync-cursor
repository are mocked so no real DB access happens.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from backlogg.scheduler import jobs as sync_jobs

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


async def test_sync_movies_limit_comes_from_settings(monkeypatch):
    """sync_movies passes settings.SEED_TOP_N_MOVIES as limit to the adapter."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_MOVIES", _CUSTOM_LIMIT)
    get_cursor, set_cursor = _cursor_patches()

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
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
        result = await sync_jobs.sync_movies()

    mock_fetch.assert_awaited_once_with(limit=_CUSTOM_LIMIT, offset=0)
    assert result["errors"] == 0


async def test_sync_series_limit_comes_from_settings(monkeypatch):
    """sync_series passes settings.SEED_TOP_N_SERIES as limit to the adapter."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_SERIES", _CUSTOM_LIMIT)
    get_cursor, set_cursor = _cursor_patches()

    with (
        patch.object(
            sync_jobs._tmdb_series,
            "get_top_series",
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
        result = await sync_jobs.sync_series()

    mock_fetch.assert_awaited_once_with(limit=_CUSTOM_LIMIT, offset=0)
    assert result["errors"] == 0


async def test_sync_books_limit_comes_from_settings(monkeypatch):
    """sync_books passes settings.SEED_TOP_N_BOOKS as limit to the adapter."""
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", _CUSTOM_LIMIT)
    get_cursor, set_cursor = _cursor_patches()

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_trending_books",
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
