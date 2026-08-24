"""Unit tests for the search fan-out ingestion helpers (Issue #14, #15).

These call ``backlogg.search.service._ingest_movies``/``_ingest_series``/
``_ingest_books``/``_ingest_games`` directly (not through ``SearchService``)
with the external adapter methods mocked, asserting that every hit returned
by the (mocked) external search — not just the top one — gets persisted, but
capped to at most ``limit`` items (Issue #15: only the hits the caller will
actually see should pay the network + DB cost), with the per-item detail
fetches (movies/series/books) running concurrently, bounded by a semaphore.

Deliberately kept in a separate module from ``tests/test_search.py``: that
module has an autouse fixture that replaces these same ``_ingest_*``
functions with no-op mocks by default (to keep unrelated search tests from
making real external calls), which would swallow the real implementation
these tests need to exercise.
"""

import asyncio
from unittest.mock import patch

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo


def _session_factory_returning(session):
    """Build a fake ``async_session_factory`` callable that yields *session*.

    Mirrors the shape of the real ``async_sessionmaker``: calling it (no
    args) returns an async context manager. Used so these tests exercise the
    real multi-item upsert loop against the shared test-fixture session
    (rollback-based isolation) instead of opening a second, unrelated
    connection via the real pool.
    """

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            return False

    def factory():
        return _SessionCM()

    return factory


async def test_ingest_movies_upserts_all_hits_from_search_page(db):
    """_ingest_movies persists every result returned by search_movie, not just the top one."""
    from backlogg.search import service

    raw_results = [
        {"id": 9001},
        {"id": 9002},
    ]

    def _detail(tmdb_id: int) -> dict:
        return {
            "id": tmdb_id,
            "title": f"Multi Hit Movie {tmdb_id}",
            "original_title": f"Multi Hit Movie {tmdb_id}",
            "overview": "x",
            "release_date": "2020-01-01",
            "runtime": 100,
            "original_language": "en",
            "poster_path": None,
            "backdrop_path": None,
            "budget": None,
            "revenue": None,
            "status": "Released",
            "vote_average": 7.0,
            "vote_count": 10,
            "genres": [],
        }

    async def fake_search_movie(q, page=1, year=None):
        return raw_results

    async def fake_get_movie_detail(tmdb_id):
        return _detail(tmdb_id)

    with (
        patch.object(service._tmdb_movies, "search_movie", new=fake_search_movie),
        patch.object(service._tmdb_movies, "get_movie_detail", new=fake_get_movie_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_movies("multi hit", page=1, limit=20)

    from backlogg.movies import repository as movies_repo_mod

    m1 = await movies_repo_mod.get_movie_by_slug(db, "multi-hit-movie-9001-2020")
    m2 = await movies_repo_mod.get_movie_by_slug(db, "multi-hit-movie-9002-2020")
    assert m1 is not None
    assert m2 is not None


async def test_ingest_series_upserts_all_hits_from_search_page(db):
    """_ingest_series persists every result returned by search_series, not just the top one."""
    from backlogg.search import service

    raw_results = [{"id": 8001}, {"id": 8002}]

    def _detail(tmdb_id: int) -> dict:
        return {
            "id": tmdb_id,
            "name": f"Multi Hit Series {tmdb_id}",
            "original_name": f"Multi Hit Series {tmdb_id}",
            "overview": "x",
            "first_air_date": "2019-01-01",
            "last_air_date": "2019-06-01",
            "number_of_seasons": 1,
            "number_of_episodes": 8,
            "status": "Ended",
            "original_language": "en",
            "poster_path": None,
            "backdrop_path": None,
            "vote_average": 7.0,
            "vote_count": 10,
            "genres": [],
        }

    async def fake_search_series(q, page=1):
        return raw_results

    async def fake_get_series_detail(tmdb_id):
        return _detail(tmdb_id)

    with (
        patch.object(service._tmdb_series, "search_series", new=fake_search_series),
        patch.object(service._tmdb_series, "get_series_detail", new=fake_get_series_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_series("multi hit", page=1, limit=20)

    s1 = await series_repo.get_series_by_slug(db, "multi-hit-series-8001-2019")
    s2 = await series_repo.get_series_by_slug(db, "multi-hit-series-8002-2019")
    assert s1 is not None
    assert s2 is not None


async def test_ingest_books_upserts_all_hits_from_search_page(db):
    """_ingest_books persists every result returned by search_book, not just the top one."""
    from backlogg.search import service

    raw_results = [
        {"key": "/works/OLMH1W", "title": "Multi Hit Book 1", "first_publish_year": 2001},
        {"key": "/works/OLMH2W", "title": "Multi Hit Book 2", "first_publish_year": 2002},
    ]

    async def fake_search_book(q, page=1, limit=1):
        return raw_results

    async def fake_get_work_detail(work_id):
        return None

    with (
        patch.object(service._ol_client, "search_book", new=fake_search_book),
        patch.object(service._ol_client, "get_work_detail", new=fake_get_work_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_books("multi hit", page=1, limit=20)

    b1 = await books_repo.get_book_by_slug(db, "multi-hit-book-1-2001")
    b2 = await books_repo.get_book_by_slug(db, "multi-hit-book-2-2002")
    assert b1 is not None
    assert b2 is not None


async def test_ingest_games_upserts_all_hits_from_search_page(db):
    """_ingest_games persists every result returned by search_games, not just the top hits."""
    from backlogg.search import service

    raw_results = [
        {"id": 7001, "name": "Multi Hit Game 1", "slug": "multi-hit-game-1"},
        {"id": 7002, "name": "Multi Hit Game 2", "slug": "multi-hit-game-2"},
    ]

    async def fake_search_games(q, limit=5, offset=0):
        return raw_results

    with (
        patch.object(service._igdb_client, "search_games", new=fake_search_games),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_games("multi hit", page=1, limit=20)

    g1 = await games_repo.get_game_by_slug(db, "multi-hit-game-1")
    g2 = await games_repo.get_game_by_slug(db, "multi-hit-game-2")
    assert g1 is not None
    assert g2 is not None


def _movie_detail(tmdb_id: int, title_prefix: str = "Capped Movie") -> dict:
    return {
        "id": tmdb_id,
        "title": f"{title_prefix} {tmdb_id}",
        "original_title": f"{title_prefix} {tmdb_id}",
        "overview": "x",
        "release_date": "2020-01-01",
        "runtime": 100,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "vote_average": 7.0,
        "vote_count": 10,
        "genres": [],
    }


def _series_detail(tmdb_id: int, title_prefix: str = "Capped Series") -> dict:
    return {
        "id": tmdb_id,
        "name": f"{title_prefix} {tmdb_id}",
        "original_name": f"{title_prefix} {tmdb_id}",
        "overview": "x",
        "first_air_date": "2019-01-01",
        "last_air_date": "2019-06-01",
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.0,
        "vote_count": 10,
        "genres": [],
    }


async def test_ingest_movies_caps_detail_fetches_to_limit(db):
    """With more hits than `limit`, only `limit` of them are detail-fetched/persisted."""
    from backlogg.search import service

    raw_results = [{"id": 9301}, {"id": 9302}, {"id": 9303}]
    called_ids: list[int] = []

    async def fake_search_movie(q, page=1, year=None):
        return raw_results

    async def fake_get_movie_detail(tmdb_id):
        called_ids.append(tmdb_id)
        return _movie_detail(tmdb_id)

    with (
        patch.object(service._tmdb_movies, "search_movie", new=fake_search_movie),
        patch.object(service._tmdb_movies, "get_movie_detail", new=fake_get_movie_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_movies("cap hit", page=1, limit=2)

    assert set(called_ids) == {9301, 9302}
    assert 9303 not in called_ids

    m1 = await movies_repo.get_movie_by_slug(db, "capped-movie-9301-2020")
    m2 = await movies_repo.get_movie_by_slug(db, "capped-movie-9302-2020")
    m3 = await movies_repo.get_movie_by_slug(db, "capped-movie-9303-2020")
    assert m1 is not None
    assert m2 is not None
    assert m3 is None


async def test_ingest_series_caps_detail_fetches_to_limit(db):
    """With more hits than `limit`, only `limit` of them are detail-fetched/persisted."""
    from backlogg.search import service

    raw_results = [{"id": 8301}, {"id": 8302}, {"id": 8303}]
    called_ids: list[int] = []

    async def fake_search_series(q, page=1):
        return raw_results

    async def fake_get_series_detail(tmdb_id):
        called_ids.append(tmdb_id)
        return _series_detail(tmdb_id)

    with (
        patch.object(service._tmdb_series, "search_series", new=fake_search_series),
        patch.object(service._tmdb_series, "get_series_detail", new=fake_get_series_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_series("cap hit", page=1, limit=2)

    assert set(called_ids) == {8301, 8302}
    assert 8303 not in called_ids

    s1 = await series_repo.get_series_by_slug(db, "capped-series-8301-2019")
    s2 = await series_repo.get_series_by_slug(db, "capped-series-8302-2019")
    s3 = await series_repo.get_series_by_slug(db, "capped-series-8303-2019")
    assert s1 is not None
    assert s2 is not None
    assert s3 is None


async def test_ingest_books_caps_detail_fetches_to_limit(db):
    """With more hits than `limit`, only `limit` of them are detail-fetched/persisted."""
    from backlogg.search import service

    raw_results = [
        {"key": "/works/OLCAP1", "title": "Capped Book 1", "first_publish_year": 2001},
        {"key": "/works/OLCAP2", "title": "Capped Book 2", "first_publish_year": 2002},
        {"key": "/works/OLCAP3", "title": "Capped Book 3", "first_publish_year": 2003},
    ]
    called_ids: list[str] = []

    async def fake_search_book(q, page=1, limit=1):
        return raw_results

    async def fake_get_work_detail(work_id):
        called_ids.append(work_id)
        return None

    with (
        patch.object(service._ol_client, "search_book", new=fake_search_book),
        patch.object(service._ol_client, "get_work_detail", new=fake_get_work_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_books("cap hit", page=1, limit=2)

    assert set(called_ids) == {"OLCAP1", "OLCAP2"}
    assert "OLCAP3" not in called_ids

    b1 = await books_repo.get_book_by_slug(db, "capped-book-1-2001")
    b2 = await books_repo.get_book_by_slug(db, "capped-book-2-2002")
    b3 = await books_repo.get_book_by_slug(db, "capped-book-3-2003")
    assert b1 is not None
    assert b2 is not None
    assert b3 is None


async def test_ingest_games_caps_upserts_to_limit(db):
    """With more hits than `limit`, only `limit` of them are upserted (IGDB has no detail call)."""
    from backlogg.search import service

    raw_results = [
        {"id": 7301, "name": "Capped Game 1", "slug": "capped-game-1"},
        {"id": 7302, "name": "Capped Game 2", "slug": "capped-game-2"},
        {"id": 7303, "name": "Capped Game 3", "slug": "capped-game-3"},
    ]

    async def fake_search_games(q, limit=5, offset=0):
        return raw_results

    with (
        patch.object(service._igdb_client, "search_games", new=fake_search_games),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_games("cap hit", page=1, limit=2)

    g1 = await games_repo.get_game_by_slug(db, "capped-game-1")
    g2 = await games_repo.get_game_by_slug(db, "capped-game-2")
    g3 = await games_repo.get_game_by_slug(db, "capped-game-3")
    assert g1 is not None
    assert g2 is not None
    assert g3 is None


async def test_ingest_movies_detail_fetches_run_concurrently(db):
    """Detail fetches for distinct movies overlap in time instead of running one-by-one."""
    from backlogg.search import service

    raw_results = [{"id": 9401}, {"id": 9402}, {"id": 9403}]
    concurrent = 0
    max_concurrent = 0

    async def fake_search_movie(q, page=1, year=None):
        return raw_results

    async def fake_get_movie_detail(tmdb_id):
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1
        return _movie_detail(tmdb_id, title_prefix="Concurrent Movie")

    with (
        patch.object(service._tmdb_movies, "search_movie", new=fake_search_movie),
        patch.object(service._tmdb_movies, "get_movie_detail", new=fake_get_movie_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_movies("concurrent hit", page=1, limit=3)

    assert max_concurrent >= 2, "detail fetches ran sequentially instead of in parallel"


async def test_ingest_series_detail_fetches_run_concurrently(db):
    """Detail fetches for distinct series overlap in time instead of running one-by-one."""
    from backlogg.search import service

    raw_results = [{"id": 8401}, {"id": 8402}, {"id": 8403}]
    concurrent = 0
    max_concurrent = 0

    async def fake_search_series(q, page=1):
        return raw_results

    async def fake_get_series_detail(tmdb_id):
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1
        return _series_detail(tmdb_id, title_prefix="Concurrent Series")

    with (
        patch.object(service._tmdb_series, "search_series", new=fake_search_series),
        patch.object(service._tmdb_series, "get_series_detail", new=fake_get_series_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_series("concurrent hit", page=1, limit=3)

    assert max_concurrent >= 2, "detail fetches ran sequentially instead of in parallel"


async def test_ingest_movies_one_detail_fetch_failure_does_not_abort_others(db):
    """A failing detail fetch for one movie must not prevent the others from being persisted."""
    from backlogg.search import service

    raw_results = [{"id": 9501}, {"id": 9502}]

    async def fake_search_movie(q, page=1, year=None):
        return raw_results

    async def fake_get_movie_detail(tmdb_id):
        if tmdb_id == 9501:
            raise RuntimeError("simulated TMDB failure")
        return _movie_detail(tmdb_id, title_prefix="Survivor Movie")

    with (
        patch.object(service._tmdb_movies, "search_movie", new=fake_search_movie),
        patch.object(service._tmdb_movies, "get_movie_detail", new=fake_get_movie_detail),
        patch("backlogg.search.service.async_session_factory", new=_session_factory_returning(db)),
    ):
        await service._ingest_movies("partial failure", page=1, limit=2)

    failed = await movies_repo.get_movie_by_slug(db, "survivor-movie-9501-2020")
    survivor = await movies_repo.get_movie_by_slug(db, "survivor-movie-9502-2020")
    assert failed is None
    assert survivor is not None
