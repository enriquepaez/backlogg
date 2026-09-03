"""Tests for the sync genre-slug-collision bugfix.

Covers the two production failure modes seen in the first real books backfill:

1. Genre slug collision — two different external genre names (e.g. "Fiction"
   vs "fiction") slugify to the same value and used to violate the unique
   slug constraint.  ``_get_or_create_genre`` must reuse the existing row
   (slug is the genre's real identity for ``?genre=<slug>`` filters).
2. Session poisoning — one item failing with an IntegrityError used to abort
   the shared session transaction, making every later item in the slice fail
   and losing the cursor commit.  A bad item must neither block the rest of
   the slice nor prevent the cursor from advancing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from backlogg.books.models import Book, BookGenre
from backlogg.books.repository import _get_or_create_genre as get_or_create_book_genre
from backlogg.books.repository import upsert_book
from backlogg.games.models import GameGenre, GamePlatform
from backlogg.games.repository import _get_or_create_genre as get_or_create_game_genre
from backlogg.games.repository import _get_or_create_platform as get_or_create_game_platform
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import get_sync_offset, set_sync_offset

# ── Repository: slug collisions reuse the existing genre (real test DB) ──────


def _book_data(slug: str, title: str, genres: list[dict]) -> dict:
    from datetime import UTC, datetime

    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": None,
        "first_publish_date": None,
        "original_language": None,
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


async def test_book_genre_same_slug_different_name_reuses_existing(db):
    """Two names that slugify identically map to a single BookGenre row."""
    first = await get_or_create_book_genre(db, "Umbra Fiction", "umbra-fiction")
    second = await get_or_create_book_genre(db, "umbra fiction", "umbra-fiction")

    assert first.id == second.id
    assert second.name == "Umbra Fiction"  # the original row is kept as-is

    result = await db.execute(
        select(func.count()).select_from(BookGenre).where(BookGenre.slug == "umbra-fiction")
    )
    assert result.scalar_one() == 1


async def test_upsert_book_colliding_genre_slugs_across_books(db):
    """Two books whose subjects collide on slug share one genre row (prod bug)."""
    book_a = await upsert_book(
        db,
        _book_data(
            "collision-alpha-2001",
            "Collision Alpha",
            [{"name": "Penumbra Tales", "slug": "penumbra-tales"}],
        ),
    )
    # This upsert used to raise IntegrityError on uq_book_genre_slug
    book_b = await upsert_book(
        db,
        _book_data(
            "collision-beta-2002",
            "Collision Beta",
            [{"name": "penumbra tales", "slug": "penumbra-tales"}],
        ),
    )

    assert {g.slug for g in book_a.genres} == {"penumbra-tales"}
    assert {g.slug for g in book_b.genres} == {"penumbra-tales"}
    assert book_a.genres[0].id == book_b.genres[0].id

    result = await db.execute(
        select(func.count()).select_from(BookGenre).where(BookGenre.slug == "penumbra-tales")
    )
    assert result.scalar_one() == 1


async def test_upsert_book_dedupes_colliding_slugs_within_one_book(db):
    """Duplicate slugs inside a single book's genre list produce one join row."""
    book = await upsert_book(
        db,
        _book_data(
            "collision-gamma-2003",
            "Collision Gamma",
            [
                {"name": "Antumbra Prose", "slug": "antumbra-prose"},
                {"name": "antumbra prose", "slug": "antumbra-prose"},
            ],
        ),
    )

    assert len(book.genres) == 1
    assert book.genres[0].slug == "antumbra-prose"


async def test_game_genre_same_slug_different_name_reuses_existing(db):
    """Game genres follow the same slug-first identity rule."""
    first = await get_or_create_game_genre(db, "Umbra Blaster", "umbra-blaster")
    second = await get_or_create_game_genre(db, "umbra blaster", "umbra-blaster")

    assert first.id == second.id

    result = await db.execute(
        select(func.count()).select_from(GameGenre).where(GameGenre.slug == "umbra-blaster")
    )
    assert result.scalar_one() == 1


async def test_game_platform_same_slug_different_name_reuses_existing(db):
    """Game platforms follow the same slug-first identity rule."""
    first = await get_or_create_game_platform(db, "Umbra Deck", "umbra-deck")
    second = await get_or_create_game_platform(db, "umbra deck", "umbra-deck")

    assert first.id == second.id

    result = await db.execute(
        select(func.count()).select_from(GamePlatform).where(GamePlatform.slug == "umbra-deck")
    )
    assert result.scalar_one() == 1


# ── Jobs: a bad item does not poison the slice nor the cursor (real test DB) ─


def _movie_detail(tmdb_id: int, title: str) -> dict:
    return {
        "id": tmdb_id,
        "title": title,
        "original_title": title,
        "overview": "Isolation test movie.",
        "release_date": "2021-01-01",
        "runtime": 100,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.0,
        "vote_count": 10,
        "genres": [],
    }


async def test_sync_movies_bad_item_does_not_block_slice_or_cursor(db, monkeypatch):
    """An IntegrityError in the middle of a slice must not block later items.

    The bad item genuinely aborts the transaction (real duplicate-key error),
    reproducing the production poisoning.  The two good items must still be
    persisted and the cursor must advance.

    Since feature 84 the slice is written in batches, so this exercises the
    per-item *fallback*: the batch route is forced to fail (the failure mode
    it is designed for — an unexpected error the pre-validation could not
    anticipate) and the job reprocesses those same items one by one, which is
    where the per-item isolation this test guards still lives.
    """
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_MOVIES", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 3)
    await set_sync_offset(db, "MOVIE", 0)

    details = {
        86101: _movie_detail(86101, "Isolation Good Alpha"),
        86102: _movie_detail(86102, "Isolation Poison Beta"),
        86103: _movie_detail(86103, "Isolation Good Gamma"),
    }

    real_upsert = sync_jobs.movies_repo.upsert_movie

    async def poisoned_upsert(session, data):
        if data["title"] == "Isolation Poison Beta":
            # Force a real IntegrityError so the transaction is aborted,
            # exactly like the duplicate genre slug did in production.
            await session.execute(
                text("INSERT INTO movie_genres (name, slug) VALUES ('__poison__', '__poison__')")
            )
            await session.execute(
                text("INSERT INTO movie_genres (name, slug) VALUES ('__poison2__', '__poison__')")
            )
        return await real_upsert(session, data)

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_top_movies",
            new_callable=AsyncMock,
            return_value=[{"id": 86101}, {"id": 86102}, {"id": 86103}],
        ),
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            side_effect=lambda tmdb_id: details[tmdb_id],
        ),
        patch.object(sync_jobs.movies_repo, "upsert_movie", new=poisoned_upsert),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch(
            "backlogg.scheduler.jobs.collect_movie_credits",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "backlogg.scheduler.jobs.bulk_load_items",
            new_callable=AsyncMock,
            side_effect=RuntimeError("batch route unavailable"),
        ),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result = await sync_jobs.sync_movies()

    assert result["synced"] == 2
    assert result["errors"] == 1
    assert result["offset"] == 0

    # Good items before AND after the poisoned one are persisted
    count_result = await db.execute(
        select(func.count())
        .select_from(Movie)
        .where(Movie.title.in_(["Isolation Good Alpha", "Isolation Good Gamma"]))
    )
    assert count_result.scalar_one() == 2

    # The poisoned item left no partial writes behind
    poison_result = await db.execute(
        select(func.count()).select_from(Movie).where(Movie.title == "Isolation Poison Beta")
    )
    assert poison_result.scalar_one() == 0

    # The cursor advanced on a healthy session (full slice of 3 fetched)
    assert await get_sync_offset(db, "MOVIE") == 3

    # _persist_cursor commits, so remove the row we left in the shared test
    # DB — other tests assert on the cursor being absent.
    await db.execute(text("DELETE FROM sync_cursors WHERE item_type = 'MOVIE'"))
    await db.commit()


async def test_sync_books_colliding_genre_slugs_across_docs(db, monkeypatch):
    """The exact production scenario: two docs that resolve to the same genre.

    Since feature 72 the labels come from a controlled vocabulary, so the two
    spellings Open Library returns ("Fiction" / "fiction") normalise onto the
    same slug before they ever reach the repository. Both books must be synced
    with errors=0 and share a single genre row.
    """
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 2)
    await set_sync_offset(db, "BOOK", 0)

    popular_raw = [
        {
            "key": "/works/OL86201W",
            "title": "Umbral Collision Alpha",
            "first_publish_year": 2001,
            "cover_i": None,
            "subject_facet": ["Fiction"],
            "author_name": [],
        },
        {
            "key": "/works/OL86202W",
            "title": "Umbral Collision Beta",
            "first_publish_year": 2002,
            "cover_i": None,
            "subject_facet": ["fiction"],
            "author_name": [],
        },
    ]

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=popular_raw,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result = await sync_jobs.sync_books()

    assert result["synced"] == 2
    assert result["errors"] == 0

    # A single genre row serves both books
    genre_result = await db.execute(
        select(func.count()).select_from(BookGenre).where(BookGenre.slug == "fiction")
    )
    assert genre_result.scalar_one() == 1

    books_result = await db.execute(
        select(Book).where(
            Book.slug.in_(["umbral-collision-alpha-2001", "umbral-collision-beta-2002"])
        )
    )
    books = list(books_result.scalars().unique().all())
    assert len(books) == 2

    # _persist_cursor commits, so remove the row we left in the shared test
    # DB — test_get_sync_offset_returns_zero_when_absent expects no BOOK row.
    await db.execute(text("DELETE FROM sync_cursors WHERE item_type = 'BOOK'"))
    await db.commit()


async def test_sync_books_persists_isbn_from_raw_doc(db, monkeypatch):
    """Bugfix: sync_books must copy `isbn` from the raw OL doc into the
    hand-built search_doc it passes to book_to_dict, so the persisted Book
    row ends up with `isbn` populated — not just an in-memory dict.

    Regression coverage for the nightly-sync path: `raw` (as returned by
    `get_popular_books`) carries `isbn`, but the `search_doc` sync_books
    reconstructs by hand used to drop that key, so every book seeded via
    the nightly job persisted with `isbn=None` even though Open Library
    provided one.
    """
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 1)
    await set_sync_offset(db, "BOOK", 0)

    popular_raw = [
        {
            "key": "/works/OL86301W",
            "title": "Isbn Sync Job Fixture",
            "first_publish_year": 2010,
            "cover_i": None,
            "author_name": [],
            "isbn": ["9780000000001", "9780000000002"],
        }
    ]

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=popular_raw,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result = await sync_jobs.sync_books()

    assert result["synced"] == 1
    assert result["errors"] == 0

    book_result = await db.execute(select(Book).where(Book.slug == "isbn-sync-job-fixture-2010"))
    book = book_result.scalar_one()
    assert book.isbn == "9780000000001"

    # _persist_cursor commits, so remove the row we left in the shared test
    # DB — test_get_sync_offset_returns_zero_when_absent expects no BOOK row.
    await db.execute(text("DELETE FROM sync_cursors WHERE item_type = 'BOOK'"))
    await db.commit()


async def test_sync_books_propagates_classification_fields_to_book_to_dict(db, monkeypatch):
    """Regression (feature 72): sync_books must copy `ddc`/`lcc`/`subject_facet`
    from the raw Open Library doc into the hand-built `search_doc` it passes to
    `book_to_dict`.

    Same class of bug as the `isbn` one above (Issue #17): the nightly job does
    not forward `raw` as-is, it rebuilds a reduced dict field by field. A field
    missing there is lost silently — the on-demand search path keeps working,
    so the catalogue only degrades for books seeded by the nightly sync. Here
    `lcc` must win over `ddc` and the persisted genres must be the controlled
    labels, proving the fields actually reached the adapter.
    """
    monkeypatch.setattr(sync_jobs.settings, "SEED_TOP_N_BOOKS", 10)
    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 2)
    await set_sync_offset(db, "BOOK", 0)

    captured_docs: list[dict] = []
    real_book_to_dict = sync_jobs._ol_client.book_to_dict

    def _spy(search_doc, work_detail=None):
        captured_docs.append(search_doc)
        return real_book_to_dict(search_doc, work_detail)

    popular_raw = [
        {
            "key": "/works/OL86401W",
            "title": "Classification Propagation Alpha",
            "first_publish_year": 2011,
            "cover_i": None,
            "author_name": [],
            "lcc": ["PZ-0007.00000000.R79835 Ha 1998"],
            "ddc": ["813/.54"],
            "subject_facet": ["Cooking"],
        },
        {
            "key": "/works/OL86402W",
            "title": "Classification Propagation Beta",
            "first_publish_year": 2012,
            "cover_i": None,
            "author_name": [],
            "ddc": ["811.54"],
            "subject_facet": ["Cooking"],
        },
    ]

    with (
        patch.object(
            sync_jobs._ol_client,
            "get_popular_books",
            new_callable=AsyncMock,
            return_value=popular_raw,
        ),
        patch.object(
            sync_jobs._ol_client,
            "get_work_detail",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(sync_jobs._ol_client, "book_to_dict", side_effect=_spy),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result = await sync_jobs.sync_books()

    assert result["synced"] == 2
    assert result["errors"] == 0

    # The reconstructed search_doc carries the three classification fields
    assert captured_docs[0]["lcc"] == ["PZ-0007.00000000.R79835 Ha 1998"]
    assert captured_docs[0]["ddc"] == ["813/.54"]
    assert captured_docs[0]["subject_facet"] == ["Cooking"]

    # ...and they actually drove the persisted genres: lcc first, ddc second
    alpha_result = await db.execute(
        select(Book)
        .where(Book.slug == "classification-propagation-alpha-2011")
        .options(selectinload(Book.genres))
    )
    alpha = alpha_result.scalar_one()
    assert {g.slug for g in alpha.genres} == {"fiction", "childrens-young-adult"}

    beta_result = await db.execute(
        select(Book)
        .where(Book.slug == "classification-propagation-beta-2012")
        .options(selectinload(Book.genres))
    )
    beta = beta_result.scalar_one()
    assert {g.slug for g in beta.genres} == {"poetry", "literature"}

    # _persist_cursor commits, so remove the row we left in the shared test
    # DB — test_get_sync_offset_returns_zero_when_absent expects no BOOK row.
    await db.execute(text("DELETE FROM sync_cursors WHERE item_type = 'BOOK'"))
    await db.commit()
