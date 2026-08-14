"""Repository tests for the content_moderation visibility rules.

Runs against the real Postgres test DB (no mocks). Verifies that the reusable
"visible review" condition (not hidden AND author not banned) is applied by
``recalculate_item_aggregates`` and the review listings.
"""

from datetime import UTC, datetime

from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import (
    get_item_by_slug,
    list_ratings_for_item,
    list_user_reviews,
    recalculate_item_aggregates,
    set_rating_hidden,
    upsert_rating,
)
from backlogg.users.repository import create_user, set_user_banned


def _movie_data(slug: str, title: str = "Mod Repo Movie") -> dict:
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


async def _make_user(db, username: str):
    return await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )


async def test_hidden_review_excluded_from_aggregate_and_listing(db):
    movie = await upsert_movie(db, _movie_data("mod-repo-movie-1"))
    user_a = await _make_user(db, "mod-repo-user-1")
    user_b = await _make_user(db, "mod-repo-user-2")

    rating_a = await upsert_rating(
        db, user_id=user_a.id, item_type="MOVIE", item_id=movie.id, score=4, review_text="A"
    )
    await upsert_rating(
        db, user_id=user_b.id, item_type="MOVIE", item_id=movie.id, score=2, review_text="B"
    )

    await recalculate_item_aggregates(db, "MOVIE", movie.id)
    refreshed = await get_item_by_slug(db, "MOVIE", "mod-repo-movie-1")
    assert refreshed.rating_count_internal == 2
    assert float(refreshed.rating_internal) == 3.0

    # Hide user_a's 4 → only user_b's 2 remains visible.
    await set_rating_hidden(db, rating_a, True)
    await recalculate_item_aggregates(db, "MOVIE", movie.id)
    refreshed = await get_item_by_slug(db, "MOVIE", "mod-repo-movie-1")
    assert refreshed.rating_count_internal == 1
    assert float(refreshed.rating_internal) == 2.0

    rows, total = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=20)
    assert total == 1
    assert all(user.id == user_b.id for _, user, _, _ in rows)


async def test_banned_author_reviews_excluded_from_aggregate_and_listings(db):
    movie = await upsert_movie(db, _movie_data("mod-repo-movie-2"))
    author = await _make_user(db, "mod-repo-author-2")

    await upsert_rating(
        db, user_id=author.id, item_type="MOVIE", item_id=movie.id, score=5, review_text="X"
    )
    await recalculate_item_aggregates(db, "MOVIE", movie.id)
    refreshed = await get_item_by_slug(db, "MOVIE", "mod-repo-movie-2")
    assert refreshed.rating_count_internal == 1

    await set_user_banned(db, author, True)
    await recalculate_item_aggregates(db, "MOVIE", movie.id)
    refreshed = await get_item_by_slug(db, "MOVIE", "mod-repo-movie-2")
    assert refreshed.rating_count_internal == 0
    assert refreshed.rating_internal is None

    _, item_total = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=20)
    assert item_total == 0

    _, user_total = await list_user_reviews(db, author.id, page=1, limit=20)
    assert user_total == 0
