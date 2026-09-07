"""Feature 91 — cross-type search without the catalog_search materialized view.

Five promises are made by this feature, and each has a test here:

1. **A freshly ingested item is searchable with no refresh step.**  This is
   the whole point of issue #28: ``REFRESH MATERIALIZED VIEW CONCURRENTLY``
   built a full 137 MB copy of the view and no longer fit in Neon's 512 MB.
   Nothing in this file calls anything between the write and the query.
2. **The per-type date column mapping survives the rewrite.**  The retired
   view folded ``release_date`` / ``first_air_date`` / ``first_publish_date``
   into one output column; the ``UNION ALL`` has to reproduce that or
   ``date_from``/``date_to`` silently stop filtering series and books.
3. **``ts_rank`` reads the stored column.**  Asserted on the compiled SQL,
   because a ``ts_rank(to_tsvector(...), ...)`` that recomputes the vector for
   every candidate row before the ``LIMIT`` would pass every behavioural test
   in the suite while throwing away the reason the column is stored at all.
4. **Order and pagination are unchanged** — ``rating_external DESC NULLS
   LAST``, then ``ts_rank``, then ``id`` (issue #14).
5. **The migration runs both ways**, against a database with rows in it.
"""

import asyncio
import os
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from backlogg.books import repository as books_repo
from backlogg.core.config import settings
from backlogg.games import repository as games_repo
from backlogg.movies import repository as movies_repo
from backlogg.search.repository import SearchRepository
from backlogg.series import repository as series_repo

# ── Fixtures: one item per type, all sharing a distinctive term ──────────────

_TERM = "Zarbolix"


def _movie(slug: str, *, title: str, released: date, rating: float | None) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A movie fixture.",
        "release_date": released,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rating,
        "rating_count_external": 10,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series(slug: str, *, title: str, aired: date, rating: float | None) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A series fixture.",
        "first_air_date": aired,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 6,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": rating,
        "rating_count_external": 10,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book(slug: str, *, title: str, published: date, rating: float | None) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A book fixture.",
        "first_publish_date": published,
        "original_language": "en",
        "poster_url": None,
        "rating_external": rating,
        "rating_count_external": 10,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game(slug: str, *, title: str, released: date, rating: float | None) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A game fixture.",
        "release_date": released,
        "game_type": "MAIN_GAME",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": rating,
        "rating_count_external": 10,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


@pytest_asyncio.fixture
async def four_types(db):
    """One item of each type, all matching ``_TERM``, each dated in its own
    per-type column and 20 years apart so a date range can isolate any one.
    """
    await movies_repo.upsert_movie(
        db, _movie("f91-movie", title=f"{_TERM} Movie", released=date(2000, 1, 1), rating=5.0)
    )
    await series_repo.upsert_series(
        db, _series("f91-series", title=f"{_TERM} Series", aired=date(2010, 1, 1), rating=6.0)
    )
    await books_repo.upsert_book(
        db, _book("f91-book", title=f"{_TERM} Book", published=date(1980, 1, 1), rating=7.0)
    )
    await games_repo.upsert_game(
        db, _game("f91-game", title=f"{_TERM} Game", released=date(2020, 1, 1), rating=8.0)
    )
    await db.flush()
    return db


# ── 1. No refresh step ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("upsert", "payload", "slug"),
    [
        ("movies", "movie", "f91-fresh-movie"),
        ("series", "series", "f91-fresh-series"),
        ("books", "book", "f91-fresh-book"),
        ("games", "game", "f91-fresh-game"),
    ],
)
async def test_freshly_ingested_item_is_searchable_without_any_refresh(db, upsert, payload, slug):
    """Write, then search. Nothing in between — that is the assertion.

    Under the materialized view this test could not have passed: the row was
    invisible to ``/search`` until ``REFRESH MATERIALIZED VIEW`` ran, and the
    refresh is exactly what no longer fits on Neon (issue #28). With
    ``search_vector`` generated on the base table, Postgres fills it inside the
    INSERT itself.
    """
    title = f"Kwyjibo {payload.title()}"
    builders = {
        "movie": (
            movies_repo.upsert_movie,
            _movie(slug, title=title, released=date(2001, 1, 1), rating=1.0),
        ),
        "series": (
            series_repo.upsert_series,
            _series(slug, title=title, aired=date(2001, 1, 1), rating=1.0),
        ),
        "book": (
            books_repo.upsert_book,
            _book(slug, title=title, published=date(2001, 1, 1), rating=1.0),
        ),
        "game": (
            games_repo.upsert_game,
            _game(slug, title=title, released=date(2001, 1, 1), rating=1.0),
        ),
    }
    func, data = builders[payload]
    await func(db, data)
    await db.flush()

    results, total = await SearchRepository(db).search(q="Kwyjibo")

    assert total >= 1
    assert slug in [row["slug"] for row in results]


async def test_no_materialized_view_is_left_in_the_database(db):
    """``catalog_search`` is gone, and with it every REFRESH in the codebase."""
    names = (
        (await db.execute(text("SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'")))
        .scalars()
        .all()
    )
    assert "catalog_search" not in names


async def test_every_content_table_has_a_stored_generated_vector_and_a_gin_index(db):
    generated = (
        (
            await db.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE column_name = 'search_vector' AND is_generated = 'ALWAYS' "
                    "AND is_nullable = 'NO' "
                    "AND table_name IN ('movies', 'series', 'books', 'games')"
                )
            )
        )
        .scalars()
        .all()
    )
    # ``is_nullable = 'NO'`` is part of the assertion, not decoration. The four
    # ORM models declare ``nullable=False`` and it is true by construction
    # (``title`` is NOT NULL everywhere and ``overview`` is COALESCEd), so a DB
    # that disagreed would make a future ``alembic revision --autogenerate``
    # emit four phantom ``alter_column`` diffs indistinguishable from real ones.
    assert sorted(generated) == ["books", "games", "movies", "series"]

    gin = (
        (
            await db.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE indexdef LIKE '%USING gin (search_vector)%' "
                    "AND tablename IN ('movies', 'series', 'books', 'games')"
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(gin) == [
        "idx_books_search_vector",
        "idx_games_search_vector",
        "idx_movies_search_vector",
        "idx_series_search_vector",
    ]


async def test_the_four_expressions_are_byte_identical(db):
    """One shared constant, four tables. If they ever drift, search starts
    behaving differently per content type with no error and no failing
    assertion anywhere else — so the drift is what is asserted.
    """
    expressions = (
        (
            await db.execute(
                text(
                    "SELECT DISTINCT pg_get_expr(d.adbin, d.adrelid) "
                    "FROM pg_attrdef d JOIN pg_attribute a "
                    "  ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
                    "WHERE a.attname = 'search_vector' "
                    "  AND d.adrelid IN ('movies'::regclass, 'series'::regclass, "
                    "                    'books'::regclass, 'games'::regclass)"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(expressions) == 1


# ── 2. The per-type date column mapping ──────────────────────────────────────


@pytest.mark.parametrize(
    ("slug", "day"),
    [
        ("f91-book", date(1980, 1, 1)),
        ("f91-movie", date(2000, 1, 1)),
        ("f91-series", date(2010, 1, 1)),
        ("f91-game", date(2020, 1, 1)),
    ],
)
async def test_date_range_filters_each_type_on_its_own_date_column(four_types, slug, day):
    """``release_date`` for movies/games, ``first_air_date`` for series,
    ``first_publish_date`` for books — the mapping the view used to do.

    A branch pointed at the wrong column would not raise: it would just stop
    matching, and the type would quietly vanish from every dated search.
    """
    results, total = await SearchRepository(four_types).search(q=_TERM, date_from=day, date_to=day)
    assert total == 1
    assert [row["slug"] for row in results] == [slug]


async def test_date_range_spanning_everything_keeps_all_four_types(four_types):
    _, total = await SearchRepository(four_types).search(
        q=_TERM, date_from=date(1900, 1, 1), date_to=date(2100, 1, 1)
    )
    assert total == 4


async def test_date_range_outside_everything_matches_nothing(four_types):
    _, total = await SearchRepository(four_types).search(
        q=_TERM, date_from=date(2050, 1, 1), date_to=date(2060, 1, 1)
    )
    assert total == 0


async def test_release_date_reported_per_type_comes_from_the_right_column(four_types):
    results, _ = await SearchRepository(four_types).search(q=_TERM, limit=10)
    by_slug = {row["slug"]: row["release_date"] for row in results}
    assert by_slug == {
        "f91-movie": date(2000, 1, 1),
        "f91-series": date(2010, 1, 1),
        "f91-book": date(1980, 1, 1),
        "f91-game": date(2020, 1, 1),
    }


# ── 3. ts_rank reads the stored column ───────────────────────────────────────


def test_ts_rank_ranks_the_stored_column_and_never_recomputes_it():
    """Asserted on the SQL, because behaviour cannot tell the two apart.

    ``ts_rank(to_tsvector(title || ...), q)`` returns the same numbers as
    ``ts_rank(search_vector, q)`` and would pass every other test in this
    file, while recomputing the vector of every candidate row *before* the
    ``LIMIT`` — the exact cost the stored column exists to avoid
    (``progress/measure_91.md``).
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy.dialects import postgresql

    from backlogg.movies.models import Movie
    from backlogg.search.repository import _row_branch, _SearchSource

    source = _SearchSource("MOVIE", Movie, "release_date")
    branch = _row_branch(
        source,
        tsquery=sa_func.plainto_tsquery("simple", "dune"),
        date_from=None,
        date_to=None,
        rating_external_min=None,
        rating_external_max=None,
    )
    sql = str(branch.compile(dialect=postgresql.dialect()))

    assert "ts_rank(movies.search_vector" in sql
    assert "ts_rank(to_tsvector" not in sql
    # The GIN index answers the filter, and it can only do that against the
    # stored column too.
    assert "movies.search_vector @@ plainto_tsquery" in sql


async def test_no_query_means_no_rank_column_at_all(four_types):
    """A pure filter query has nothing to rank, so it must not pay for a rank."""
    results, total = await SearchRepository(four_types).search(q=None, date_from=date(1900, 1, 1))
    assert total == 4
    # Ordered by rating alone, best first.
    assert [row["slug"] for row in results] == [
        "f91-game",
        "f91-book",
        "f91-series",
        "f91-movie",
    ]


async def test_item_type_prunes_the_union_instead_of_filtering_after_it(four_types):
    """A typed search must not read the three tables it cannot return."""
    results, total = await SearchRepository(four_types).search(q=_TERM, item_type="book")
    assert total == 1
    assert [row["item_type"] for row in results] == ["BOOK"]

    plan = (
        (
            await four_types.execute(
                text(
                    "EXPLAIN SELECT id FROM books WHERE search_vector @@ "
                    "plainto_tsquery('simple', :q)"
                ),
                {"q": _TERM},
            )
        )
        .scalars()
        .all()
    )
    # Sanity: the branch is a plain single-table scan, no view in sight.
    assert not any("catalog_search" in line for line in plan)


# ── 4. Order and pagination ──────────────────────────────────────────────────


async def test_rating_external_is_the_primary_sort_key(four_types):
    results, total = await SearchRepository(four_types).search(q=_TERM, limit=10)
    assert total == 4
    assert [row["rating_external"] for row in results] == [8.0, 7.0, 6.0, 5.0]


async def test_unrated_items_sort_last_and_ts_rank_orders_them(db):
    """``NULLS LAST`` plus the ts_rank tie-break inside the NULL band.

    ``progress/measure_91.md`` measured this band at 8-44 % of the matches in
    production: every one of them ties on ``rating_external``, so ts_rank is
    the *only* thing ordering them. A shorter title carries the term with
    more weight, so it must come first.
    """
    await movies_repo.upsert_movie(
        db, _movie("f91-rank-short", title="Blorptastic", released=date(2000, 1, 1), rating=None)
    )
    await movies_repo.upsert_movie(
        db,
        _movie(
            "f91-rank-long",
            title="Blorptastic And A Great Many Other Words Besides These Ones Here",
            released=date(2000, 1, 1),
            rating=None,
        ),
    )
    await movies_repo.upsert_movie(
        db,
        _movie("f91-rank-rated", title="Blorptastic Rated", released=date(2000, 1, 1), rating=9.0),
    )
    await db.flush()

    results, total = await SearchRepository(db).search(q="Blorptastic", item_type="movie")

    assert total == 3
    assert results[0]["slug"] == "f91-rank-rated"
    assert results[0]["rating_external"] == 9.0
    assert [row["slug"] for row in results[1:]] == ["f91-rank-short", "f91-rank-long"]


async def test_pagination_reports_total_before_paginating_and_never_repeats(four_types):
    seen: list[str] = []
    for page in (1, 2, 3, 4):
        results, total = await SearchRepository(four_types).search(q=_TERM, page=page, limit=1)
        assert total == 4
        assert len(results) == 1
        seen.append(results[0]["slug"])

    assert seen == ["f91-game", "f91-book", "f91-series", "f91-movie"]
    _, total = await SearchRepository(four_types).search(q=_TERM, page=5, limit=1)
    assert total == 4


async def test_pagination_is_stable_across_types_that_share_an_id(db):
    """Issue #14 under a UNION ALL: ``id`` is unique per table, not across the
    four, so two rows that tie on rating and rank can share it. ``item_type``
    is the final tie-breaker that keeps the page deterministic.
    """
    await movies_repo.upsert_movie(
        db, _movie("f91-tie-movie", title="Grunkle", released=date(2000, 1, 1), rating=5.0)
    )
    await books_repo.upsert_book(
        db, _book("f91-tie-book", title="Grunkle", published=date(2000, 1, 1), rating=5.0)
    )
    await db.flush()

    pages = [
        [row["slug"] for row in (await SearchRepository(db).search(q="Grunkle", limit=10))[0]]
        for _ in range(5)
    ]
    assert all(page == pages[0] for page in pages)
    assert sorted(pages[0]) == ["f91-tie-book", "f91-tie-movie"]


async def test_rating_range_filter_still_applies_across_types(four_types):
    results, total = await SearchRepository(four_types).search(
        q=_TERM, rating_external_min=6.0, rating_external_max=7.0
    )
    assert total == 2
    assert sorted(row["slug"] for row in results) == ["f91-book", "f91-series"]


async def test_punctuation_stripped_title_variant_still_matches(db):
    """Issue #13's normalization travelled with the expression: a query without
    punctuation still finds a punctuated title.
    """
    await movies_repo.upsert_movie(
        db, _movie("f91-punct", title="Zorp-Man", released=date(2000, 1, 1), rating=5.0)
    )
    await db.flush()

    _, total = await SearchRepository(db).search(q="Zorpman", item_type="movie")
    assert total == 1


# ── 5. The migration, both ways, with rows in the database ───────────────────

_SCRATCH_DB = "backlogg_migration_0038"

_SEED_AT_0037 = (
    """
INSERT INTO movies (id, title, slug, overview, release_date, rating_external,
                    rating_count_internal, locked_fields, last_synced_at)
VALUES (1, 'Spider-Man', 'spider-man-2002', 'A movie.', '2002-05-03', 7.3, 0, '{}', NOW())
""",
    """
INSERT INTO series (id, title, slug, overview, first_air_date, rating_external,
                    rating_count_internal, locked_fields, last_synced_at)
VALUES (2, 'Firefly', 'firefly-2002', 'A series.', '2002-09-20', 8.6, 0, '{}', NOW())
""",
    """
INSERT INTO books (id, title, slug, overview, first_publish_date, rating_external,
                   rating_count_internal, locked_fields, last_synced_at)
VALUES (3, 'Dune', 'dune-1965', 'A book.', '1965-08-01', 8.7, 0, '{}', NOW())
""",
    """
INSERT INTO games (id, title, slug, overview, release_date, game_type,
                   rating_count_internal, locked_fields, last_synced_at)
VALUES (4, 'Portal', 'portal-2007', 'A game.', '2007-10-10', 'MAIN_GAME', 0, '{}', NOW())
""",
)


def _scratch_url() -> str:
    base = settings.TEST_DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{_SCRATCH_DB}"


async def _admin_execute(statement: str) -> None:
    """``CREATE``/``DROP DATABASE`` cannot run inside a transaction."""
    engine = create_async_engine(
        f"{settings.TEST_DATABASE_URL.rsplit('/', 1)[0]}/postgres",
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _run_on_scratch(statements: tuple[str, ...]) -> None:
    engine = create_async_engine(_scratch_url())
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _read_scratch(query: str) -> list[tuple]:
    engine = create_async_engine(_scratch_url())
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(query))).all()]
    finally:
        await engine.dispose()


def _alembic(direction: str, revision: str) -> None:
    """``alembic/env.py`` reads ``DATABASE_URL`` from the environment and spins
    its own event loop, which is why this test is synchronous.
    """
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = _scratch_url()
    try:
        getattr(command, direction)(Config("alembic.ini"), revision)
    finally:
        os.environ["DATABASE_URL"] = previous


def test_migration_0038_upgrades_and_downgrades_with_data():
    """0037 -> 0038 -> 0037 on a database with a row of each type in it.

    Pinned to "0038", not "head": this test asserts the shape 0038 produces,
    so the day 0039 lands it has to keep testing 0037 -> 0038 instead of
    silently starting to test whatever came after.

    The three things the deploy depends on:

    * the ``ALTER``s backfill the vector for rows that already existed (the
      85.530 already in production), and keep filling it for rows written
      *after* the migration with no refresh anywhere;
    * the view and its ``REFRESH`` are gone;
    * the downgrade puts the view back **with its unique index**, without
      which ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` refuses to run at all
      (that was migration 0007) — so the downgrade is exercised by actually
      running that refresh.
    """
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
    asyncio.run(_admin_execute(f'CREATE DATABASE "{_SCRATCH_DB}"'))
    try:
        _alembic("upgrade", "0037")
        asyncio.run(_run_on_scratch(_SEED_AT_0037))
        assert asyncio.run(_read_scratch("SELECT COUNT(*) FROM pg_matviews")) == [(1,)]

        _alembic("upgrade", "0038")

        # The view is gone.
        assert asyncio.run(
            _read_scratch("SELECT to_regclass('public.catalog_search') IS NULL")
        ) == [(True,)]

        # Pre-existing rows were backfilled by the rewrite, all four of them.
        assert asyncio.run(
            _read_scratch(
                "SELECT COUNT(*) FROM ("
                "  SELECT search_vector FROM movies UNION ALL"
                "  SELECT search_vector FROM series UNION ALL"
                "  SELECT search_vector FROM books  UNION ALL"
                "  SELECT search_vector FROM games"
                ") v WHERE search_vector IS NOT NULL AND search_vector <> ''::tsvector"
            )
        ) == [(4,)]

        # Issue #13's punctuation variant travelled with the expression.
        assert asyncio.run(
            _read_scratch(
                "SELECT COUNT(*) FROM movies "
                "WHERE search_vector @@ plainto_tsquery('simple', 'spiderman')"
            )
        ) == [(1,)]

        # A row written *after* the migration gets its vector with no refresh.
        asyncio.run(
            _run_on_scratch(
                (
                    "INSERT INTO movies (id, title, slug, overview, release_date, "
                    "rating_count_internal, locked_fields, last_synced_at) "
                    "VALUES (99, 'Arrival', 'arrival-2016', 'A movie.', '2016-11-11', "
                    "0, '{}', NOW())",
                )
            )
        )
        assert asyncio.run(
            _read_scratch(
                "SELECT slug FROM movies "
                "WHERE search_vector @@ plainto_tsquery('simple', 'arrival')"
            )
        ) == [("arrival-2016",)]

        # The generated column cannot be written by hand — that is what makes
        # "nothing to refresh" a guarantee rather than a convention.
        with pytest.raises(Exception, match="generated column"):
            asyncio.run(
                _run_on_scratch(("UPDATE movies SET search_vector = ''::tsvector WHERE id = 1",))
            )

        _alembic("downgrade", "0037")

        assert asyncio.run(_read_scratch("SELECT matviewname FROM pg_matviews")) == [
            ("catalog_search",)
        ]
        assert asyncio.run(
            _read_scratch(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'catalog_search' ORDER BY indexname"
            )
        ) == [
            ("idx_catalog_search_type",),
            ("idx_catalog_search_vector",),
            ("uq_catalog_search_type_id",),
        ]
        # The generated columns are gone from all four tables.
        assert asyncio.run(
            _read_scratch(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE column_name = 'search_vector' "
                "AND table_name IN ('movies', 'series', 'books', 'games')"
            )
        ) == [(0,)]
        # And the restored view is refreshable, which is the whole reason
        # uq_catalog_search_type_id has to come back with it.
        asyncio.run(_run_on_scratch(("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search",)))
        assert asyncio.run(_read_scratch("SELECT COUNT(*) FROM catalog_search")) == [(5,)]
    finally:
        asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
