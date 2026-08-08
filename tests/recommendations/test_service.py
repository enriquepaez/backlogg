"""Service tests for backlogg/recommendations/service.py.

The external similar-items adapters (TMDB, reused via feature 16) are mocked in
every test that touches movie/series fan-out — no network is ever hit. Covers:
seeding from high ratings and from the library, exclusion of already-seen
items, the popular fallback when there are no seeds, the ``?type=`` filter, and
the "no external fan-out when enough local candidates" guarantee.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

from backlogg.books.repository import upsert_book
from backlogg.library.repository import upsert_library_entry
from backlogg.movies import service as movies_service
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.recommendations import service
from backlogg.users.models import User
from backlogg.users.repository import create_user


def _movie_data(slug: str, genres: list[dict], title: str, rating: float | None = 7.0) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": date(2020, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": "https://img/poster.jpg",
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rating,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


def _book_data(slug: str, genres: list[dict], title: str, rating: float | None = 7.0) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": date(2019, 1, 1),
        "original_language": "en",
        "poster_url": "https://img/book.jpg",
        "rating_external": rating,
        "rating_count_external": 500,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres,
    }


async def _make_user(db, username: str) -> User:
    return await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )


# ── Seeding from high ratings ────────────────────────────────────────────


async def test_seed_from_high_rating_movie(db):
    genre = [{"name": "Rec Action", "slug": "rec-action-1"}]
    seed = await upsert_movie(db, _movie_data("rec-seed-movie-1", genre, "Rec Seed Movie 1"))
    candidate = await upsert_movie(db, _movie_data("rec-cand-movie-1", genre, "Rec Cand Movie 1"))
    user = await _make_user(db, "rec-user-1")
    await upsert_rating(db, user.id, "MOVIE", seed.id, 5, None)

    with patch.object(
        movies_service._tmdb,
        "get_movie_recommendations",
        new_callable=AsyncMock,
        return_value=[],
    ):
        out = await service.get_recommendations(db, user, "movie", page=1, limit=20)

    slugs = {r.slug for r in out.results}
    assert "rec-cand-movie-1" in slugs
    assert candidate.slug in slugs
    cand = next(r for r in out.results if r.slug == "rec-cand-movie-1")
    assert cand.reason == "Because you rated Rec Seed Movie 1"
    assert cand.item_type == "MOVIE"
    assert cand.poster_url is not None


# ── Seeding from the library ─────────────────────────────────────────────


async def test_seed_from_library_book(db):
    genre = [{"name": "Rec Fantasy", "slug": "rec-fantasy-1"}]
    seed = await upsert_book(db, _book_data("rec-seed-book-1", genre, "Rec Seed Book 1"))
    await upsert_book(db, _book_data("rec-cand-book-1", genre, "Rec Cand Book 1"))
    user = await _make_user(db, "rec-user-2")
    await upsert_library_entry(db, user.id, "BOOK", seed.id, "completed")

    out = await service.get_recommendations(db, user, "book", page=1, limit=20)

    slugs = {r.slug for r in out.results}
    assert "rec-cand-book-1" in slugs
    cand = next(r for r in out.results if r.slug == "rec-cand-book-1")
    assert cand.reason == "Because Rec Seed Book 1 is in your library"
    assert cand.item_type == "BOOK"


# ── Exclusion of already-seen items ──────────────────────────────────────


async def test_excludes_already_seen_items(db):
    genre = [{"name": "Rec Sci Fi", "slug": "rec-scifi-1"}]
    seed = await upsert_book(db, _book_data("rec-seed-book-2", genre, "Rec Seed Book 2"))
    rated_cand = await upsert_book(db, _book_data("rec-cand-book-2", genre, "Rec Cand Book 2"))
    fresh_cand = await upsert_book(db, _book_data("rec-cand-book-3", genre, "Rec Cand Book 3"))
    user = await _make_user(db, "rec-user-3")

    await upsert_library_entry(db, user.id, "BOOK", seed.id, "want")
    # rated_cand shares the genre but the user already rated it -> excluded.
    await upsert_rating(db, user.id, "BOOK", rated_cand.id, 3, None)

    out = await service.get_recommendations(db, user, "book", page=1, limit=20)

    slugs = {r.slug for r in out.results}
    assert fresh_cand.slug in slugs
    assert rated_cand.slug not in slugs
    assert seed.slug not in slugs


# ── Popular fallback when the user has no seeds ──────────────────────────


async def test_fallback_popular_when_no_seeds(db):
    await upsert_book(db, _book_data("rec-pop-book-1", [], "Rec Pop Book 1", rating=9.5))
    await upsert_book(db, _book_data("rec-pop-book-2", [], "Rec Pop Book 2", rating=8.0))
    user = await _make_user(db, "rec-user-4")

    out = await service.get_recommendations(db, user, "book", page=1, limit=20)

    assert len(out.results) >= 1
    slugs = {r.slug for r in out.results}
    assert "rec-pop-book-1" in slugs
    assert all(r.reason == "Popular right now" for r in out.results)
    # Highest external rating first.
    assert out.results[0].slug == "rec-pop-book-1"


# ── ?type= filter ────────────────────────────────────────────────────────


async def test_type_filter_restricts_to_one_type(db):
    m_genre = [{"name": "Rec Drama", "slug": "rec-drama-1"}]
    b_genre = [{"name": "Rec History", "slug": "rec-history-1"}]
    seed_movie = await upsert_movie(
        db, _movie_data("rec-seed-movie-3", m_genre, "Rec Seed Movie 3")
    )
    await upsert_movie(db, _movie_data("rec-cand-movie-3", m_genre, "Rec Cand Movie 3"))
    seed_book = await upsert_book(db, _book_data("rec-seed-book-4", b_genre, "Rec Seed Book 4"))
    await upsert_book(db, _book_data("rec-cand-book-4", b_genre, "Rec Cand Book 4"))
    user = await _make_user(db, "rec-user-5")

    await upsert_rating(db, user.id, "MOVIE", seed_movie.id, 5, None)
    await upsert_library_entry(db, user.id, "BOOK", seed_book.id, "completed")

    out = await service.get_recommendations(db, user, "book", page=1, limit=20)

    assert len(out.results) >= 1
    assert all(r.item_type == "BOOK" for r in out.results)
    slugs = {r.slug for r in out.results}
    assert "rec-cand-book-4" in slugs
    assert "rec-cand-movie-3" not in slugs


# ── No external fan-out when enough local candidates ─────────────────────


async def test_no_external_fanout_when_enough_local_candidates(db):
    genre = [{"name": "Rec Thriller", "slug": "rec-thriller-1"}]
    seed = await upsert_movie(db, _movie_data("rec-seed-movie-4", genre, "Rec Seed Movie 4"))
    await upsert_movie(db, _movie_data("rec-cand-movie-4", genre, "Rec Cand Movie 4", rating=8.0))
    await upsert_movie(db, _movie_data("rec-cand-movie-5", genre, "Rec Cand Movie 5", rating=7.5))
    user = await _make_user(db, "rec-user-6")
    await upsert_rating(db, user.id, "MOVIE", seed.id, 5, None)

    with patch.object(
        movies_service._tmdb,
        "get_movie_recommendations",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_recs:
        out = await service.get_recommendations(db, user, "movie", page=1, limit=2)

    # Two local genre-overlap candidates already satisfy the request → no TMDB.
    mock_recs.assert_not_called()
    assert len(out.results) == 2
    assert {r.slug for r in out.results} == {"rec-cand-movie-4", "rec-cand-movie-5"}


async def test_external_fanout_when_local_candidates_insufficient(db):
    genre = [{"name": "Rec Mystery", "slug": "rec-mystery-1"}]
    seed = await upsert_movie(db, _movie_data("rec-seed-movie-5", genre, "Rec Seed Movie 5"))
    user = await _make_user(db, "rec-user-7")
    await upsert_rating(db, user.id, "MOVIE", seed.id, 5, None)
    from backlogg.shared.external_ids import upsert_external_id

    await upsert_external_id(db, "MOVIE", seed.id, "TMDB", "8888801")

    rec_item = {"id": 8888810, "title": "External Rec Movie", "release_date": "2015-05-05"}
    rec_detail = {
        "id": 8888810,
        "title": "External Rec Movie",
        "original_title": "External Rec Movie",
        "overview": "",
        "release_date": "2015-05-05",
        "runtime": 100,
        "original_language": "en",
        "poster_path": "/ext.jpg",
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 8.0,
        "vote_count": 2000,
        "genres": [],
    }

    with (
        patch.object(
            movies_service._tmdb,
            "get_movie_recommendations",
            new_callable=AsyncMock,
            return_value=[rec_item],
        ) as mock_recs,
        patch.object(
            movies_service._tmdb,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value=rec_detail,
        ),
    ):
        out = await service.get_recommendations(db, user, "movie", page=1, limit=20)

    mock_recs.assert_called()
    slugs = {r.slug for r in out.results}
    assert "external-rec-movie-2015" in slugs
    ext = next(r for r in out.results if r.slug == "external-rec-movie-2015")
    assert ext.reason == "Because you rated Rec Seed Movie 5"
