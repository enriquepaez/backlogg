"""Repository tests for backlogg/feed/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers both tabs (following/popular), pagination, the 30-day popular window
and the "caller with no follows → empty list" acceptance criterion.
"""

from datetime import UTC, datetime, timedelta

from backlogg.feed.repository import list_following_feed, list_popular_feed
from backlogg.follows.repository import create_follow_if_not_exists
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import create_like_if_not_exists, upsert_rating
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Feed Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": None,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series_data(slug: str, title: str = "Feed Series") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "first_air_date": None,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


async def _make_user(db, username: str) -> int:
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": f"Display {username}",
        },
    )
    return user.id


async def _rate(db, user_id, item_type, item_id, score, text, *, created_at=None):
    rating = await upsert_rating(
        db, user_id=user_id, item_type=item_type, item_id=item_id, score=score, review_text=text
    )
    if created_at is not None:
        rating.created_at = created_at
        await db.flush()
    return rating


# ── following tab ─────────────────────────────────────────────────────────


async def test_following_feed_returns_followed_reviews_reverse_chron(db):
    caller = await _make_user(db, "feed-caller-1")
    author_a = await _make_user(db, "feed-author-1")
    author_b = await _make_user(db, "feed-author-2")
    movie = await upsert_movie(db, _movie_data("feed-movie-1"))
    series = await upsert_series(db, _series_data("feed-series-1"))

    await create_follow_if_not_exists(db, follower_id=caller, followed_id=author_a)
    await create_follow_if_not_exists(db, follower_id=caller, followed_id=author_b)

    now = datetime.now(UTC)
    await _rate(db, author_a, "MOVIE", movie.id, 5, "older", created_at=now - timedelta(hours=2))
    await _rate(db, author_b, "SERIES", series.id, 4, "newer", created_at=now - timedelta(hours=1))

    rows, total = await list_following_feed(db, caller, page=1, limit=20)
    assert total == 2
    # Reverse-chronological: newest (series) first.
    assert rows[0].review_text == "newer"
    assert rows[0].item_type == "SERIES"
    assert rows[1].review_text == "older"
    # Author fields resolved in-SQL.
    assert rows[0].username == "feed-author-2"
    assert rows[0].display_name == "Display feed-author-2"


async def test_following_feed_excludes_non_followed_authors(db):
    caller = await _make_user(db, "feed-caller-2")
    followed = await _make_user(db, "feed-author-3")
    stranger = await _make_user(db, "feed-author-4")
    movie = await upsert_movie(db, _movie_data("feed-movie-2"))

    await create_follow_if_not_exists(db, follower_id=caller, followed_id=followed)

    await _rate(db, followed, "MOVIE", movie.id, 5, "followed review")
    await _rate(db, stranger, "MOVIE", movie.id, 1, "stranger review")

    rows, total = await list_following_feed(db, caller, page=1, limit=20)
    assert total == 1
    assert rows[0].review_text == "followed review"


async def test_following_feed_no_follows_returns_empty(db):
    caller = await _make_user(db, "feed-caller-3")
    author = await _make_user(db, "feed-author-5")
    movie = await upsert_movie(db, _movie_data("feed-movie-3"))
    await _rate(db, author, "MOVIE", movie.id, 4, "not followed")

    rows, total = await list_following_feed(db, caller, page=1, limit=20)
    assert total == 0
    assert rows == []


async def test_following_feed_pagination(db):
    caller = await _make_user(db, "feed-caller-4")
    author = await _make_user(db, "feed-author-6")
    await create_follow_if_not_exists(db, follower_id=caller, followed_id=author)

    now = datetime.now(UTC)
    m1 = await upsert_movie(db, _movie_data("feed-movie-4a"))
    m2 = await upsert_movie(db, _movie_data("feed-movie-4b"))
    m3 = await upsert_movie(db, _movie_data("feed-movie-4c"))
    await _rate(db, author, "MOVIE", m1.id, 3, "r1", created_at=now - timedelta(hours=3))
    await _rate(db, author, "MOVIE", m2.id, 3, "r2", created_at=now - timedelta(hours=2))
    await _rate(db, author, "MOVIE", m3.id, 3, "r3", created_at=now - timedelta(hours=1))

    page1, total = await list_following_feed(db, caller, page=1, limit=2)
    assert total == 3
    assert len(page1) == 2
    assert page1[0].review_text == "r3"

    page2, _ = await list_following_feed(db, caller, page=2, limit=2)
    assert len(page2) == 1
    assert page2[0].review_text == "r1"


# ── popular tab ───────────────────────────────────────────────────────────


async def test_popular_feed_orders_by_like_count_then_recency(db):
    author = await _make_user(db, "feed-author-7")
    liker_a = await _make_user(db, "feed-liker-1")
    liker_b = await _make_user(db, "feed-liker-2")
    m_low = await upsert_movie(db, _movie_data("feed-movie-5a"))
    m_high = await upsert_movie(db, _movie_data("feed-movie-5b"))

    now = datetime.now(UTC)
    # The less-liked review is newer, so only like_count ordering can put the
    # more-liked (older) one first.
    high = await _rate(
        db, author, "MOVIE", m_high.id, 5, "popular", created_at=now - timedelta(hours=2)
    )
    await _rate(
        db, author, "MOVIE", m_low.id, 4, "less popular", created_at=now - timedelta(hours=1)
    )

    await create_like_if_not_exists(db, user_id=liker_a, rating_id=high.id)
    await create_like_if_not_exists(db, user_id=liker_b, rating_id=high.id)

    rows, total = await list_popular_feed(db, page=1, limit=20)
    assert total == 2
    assert rows[0].review_text == "popular"
    assert rows[0].like_count == 2
    assert rows[1].like_count == 0


async def test_popular_feed_excludes_reviews_older_than_30_days(db):
    author = await _make_user(db, "feed-author-8")
    m_recent = await upsert_movie(db, _movie_data("feed-movie-6a"))
    m_old = await upsert_movie(db, _movie_data("feed-movie-6b"))

    now = datetime.now(UTC)
    await _rate(db, author, "MOVIE", m_recent.id, 5, "recent", created_at=now - timedelta(days=5))
    await _rate(db, author, "MOVIE", m_old.id, 5, "ancient", created_at=now - timedelta(days=40))

    rows, total = await list_popular_feed(db, page=1, limit=20)
    assert total == 1
    assert rows[0].review_text == "recent"


async def test_popular_feed_pagination(db):
    author = await _make_user(db, "feed-author-9")
    now = datetime.now(UTC)
    m1 = await upsert_movie(db, _movie_data("feed-movie-7a"))
    m2 = await upsert_movie(db, _movie_data("feed-movie-7b"))
    m3 = await upsert_movie(db, _movie_data("feed-movie-7c"))
    await _rate(db, author, "MOVIE", m1.id, 3, "p1", created_at=now - timedelta(hours=3))
    await _rate(db, author, "MOVIE", m2.id, 3, "p2", created_at=now - timedelta(hours=2))
    await _rate(db, author, "MOVIE", m3.id, 3, "p3", created_at=now - timedelta(hours=1))

    page1, total = await list_popular_feed(db, page=1, limit=2)
    assert total == 3
    assert len(page1) == 2

    page2, _ = await list_popular_feed(db, page=2, limit=2)
    assert len(page2) == 1
