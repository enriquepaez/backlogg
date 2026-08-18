"""Repository tests for backlogg/ratings/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers aggregate recalculation (the acceptance criterion that most needs
DB-level verification) plus the upsert/list/like helpers.
"""

from datetime import UTC, datetime

from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import (
    count_likes,
    create_like_if_not_exists,
    delete_like_if_exists,
    delete_rating,
    get_item_by_slug,
    get_like,
    get_rating,
    get_rating_by_id,
    list_ratings_for_item,
    list_user_reviews,
    recalculate_item_aggregates,
    upsert_rating,
)
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Repo Rating Movie") -> dict:
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


def _series_data(slug: str, title: str = "Repo Rating Series") -> dict:
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
            "display_name": username,
        },
    )
    return user.id


# ── get_item_by_slug ─────────────────────────────────────────────────────


async def test_get_item_by_slug_found(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-1"))
    found = await get_item_by_slug(db, "MOVIE", "repo-rating-movie-1")
    assert found is not None
    assert found.id == movie.id


async def test_get_item_by_slug_not_found(db):
    found = await get_item_by_slug(db, "MOVIE", "does-not-exist-repo-rating-movie")
    assert found is None


# ── upsert_rating / get_rating ───────────────────────────────────────────


async def test_upsert_rating_creates(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-2"))
    user_id = await _make_user(db, "rating-repo-user-1")

    rating = await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=4, review_text="Good"
    )

    assert rating.id is not None
    assert rating.score == 4
    assert rating.review_text == "Good"


async def test_upsert_rating_accepts_half_star_score(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-17"))
    user_id = await _make_user(db, "rating-repo-user-26")

    rating = await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=3.5, review_text="Half star"
    )

    assert float(rating.score) == 3.5


async def test_upsert_rating_idempotent_updates_existing_row(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-3"))
    user_id = await _make_user(db, "rating-repo-user-2")

    first = await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=3, review_text="Ok"
    )
    second = await upsert_rating(
        db,
        user_id=user_id,
        item_type="MOVIE",
        item_id=movie.id,
        score=5,
        review_text="Actually great",
    )

    assert first.id == second.id
    assert second.score == 5
    assert second.review_text == "Actually great"

    fetched = await get_rating(db, user_id=user_id, item_type="MOVIE", item_id=movie.id)
    assert fetched is not None
    assert fetched.id == second.id


async def test_get_rating_not_found(db):
    result = await get_rating(db, user_id=999_999, item_type="MOVIE", item_id=999_999)
    assert result is None


# ── recalculate_item_aggregates ──────────────────────────────────────────


async def test_recalculate_item_aggregates_computes_avg_and_count(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-4"))
    user_a = await _make_user(db, "rating-repo-user-3")
    user_b = await _make_user(db, "rating-repo-user-4")

    await upsert_rating(
        db, user_id=user_a, item_type="MOVIE", item_id=movie.id, score=4, review_text=None
    )
    await upsert_rating(
        db, user_id=user_b, item_type="MOVIE", item_id=movie.id, score=2, review_text=None
    )

    await recalculate_item_aggregates(db, "MOVIE", movie.id)

    refreshed = await get_item_by_slug(db, "MOVIE", "repo-rating-movie-4")
    assert refreshed.rating_count_internal == 2
    assert float(refreshed.rating_internal) == 3.0


async def test_recalculate_item_aggregates_computes_avg_with_mixed_decimal_scores(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-16"))
    user_a = await _make_user(db, "rating-repo-user-24")
    user_b = await _make_user(db, "rating-repo-user-25")

    await upsert_rating(
        db, user_id=user_a, item_type="MOVIE", item_id=movie.id, score=3.5, review_text=None
    )
    await upsert_rating(
        db, user_id=user_b, item_type="MOVIE", item_id=movie.id, score=4, review_text=None
    )

    await recalculate_item_aggregates(db, "MOVIE", movie.id)

    refreshed = await get_item_by_slug(db, "MOVIE", "repo-rating-movie-16")
    assert refreshed.rating_count_internal == 2
    assert float(refreshed.rating_internal) == 3.75


async def test_recalculate_item_aggregates_ignores_null_scores(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-5"))
    user_a = await _make_user(db, "rating-repo-user-5")
    user_b = await _make_user(db, "rating-repo-user-6")

    await upsert_rating(
        db, user_id=user_a, item_type="MOVIE", item_id=movie.id, score=5, review_text=None
    )
    await upsert_rating(
        db, user_id=user_b, item_type="MOVIE", item_id=movie.id, score=None, review_text="Text only"
    )

    await recalculate_item_aggregates(db, "MOVIE", movie.id)

    refreshed = await get_item_by_slug(db, "MOVIE", "repo-rating-movie-5")
    assert refreshed.rating_count_internal == 1
    assert float(refreshed.rating_internal) == 5.0


async def test_recalculate_item_aggregates_resets_when_all_ratings_removed(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-6"))
    user_id = await _make_user(db, "rating-repo-user-7")

    rating = await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=3, review_text=None
    )
    await recalculate_item_aggregates(db, "MOVIE", movie.id)

    await delete_rating(db, rating)
    await recalculate_item_aggregates(db, "MOVIE", movie.id)

    refreshed = await get_item_by_slug(db, "MOVIE", "repo-rating-movie-6")
    assert refreshed.rating_count_internal == 0
    assert refreshed.rating_internal is None


# ── list_ratings_for_item ────────────────────────────────────────────────


async def test_list_ratings_for_item_pagination_and_like_count(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-7"))
    user_a = await _make_user(db, "rating-repo-user-8")
    user_b = await _make_user(db, "rating-repo-user-9")

    rating_a = await upsert_rating(
        db, user_id=user_a, item_type="MOVIE", item_id=movie.id, score=5, review_text="A"
    )
    await upsert_rating(
        db, user_id=user_b, item_type="MOVIE", item_id=movie.id, score=4, review_text="B"
    )

    await create_like_if_not_exists(db, user_id=user_b, rating_id=rating_a.id)

    rows, total = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=1)
    assert total == 2
    assert len(rows) == 1
    # Most recent first — rating from user_b was written last.
    rating, user, like_count, liked_by_viewer = rows[0]
    assert user.id == user_b
    assert like_count == 0
    assert liked_by_viewer is False

    rows_page2, _ = await list_ratings_for_item(db, "MOVIE", movie.id, page=2, limit=1)
    rating2, user2, like_count2, liked_by_viewer2 = rows_page2[0]
    assert user2.id == user_a
    assert like_count2 == 1
    assert liked_by_viewer2 is False


async def test_list_ratings_for_item_liked_by_viewer_true_for_caller_who_liked(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-13"))
    author = await _make_user(db, "rating-repo-user-18")
    liker = await _make_user(db, "rating-repo-user-19")

    rating = await upsert_rating(
        db, user_id=author, item_type="MOVIE", item_id=movie.id, score=5, review_text="Great"
    )
    await create_like_if_not_exists(db, user_id=liker, rating_id=rating.id)

    rows, _ = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=20, caller_id=liker)
    _, _, _, liked_by_viewer = rows[0]
    assert liked_by_viewer is True


async def test_list_ratings_for_item_liked_by_viewer_false_for_caller_who_did_not_like(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-14"))
    author = await _make_user(db, "rating-repo-user-20")
    other = await _make_user(db, "rating-repo-user-21")

    await upsert_rating(
        db, user_id=author, item_type="MOVIE", item_id=movie.id, score=5, review_text="Great"
    )

    rows, _ = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=20, caller_id=other)
    _, _, _, liked_by_viewer = rows[0]
    assert liked_by_viewer is False


async def test_list_ratings_for_item_liked_by_viewer_false_for_anonymous_caller(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-15"))
    author = await _make_user(db, "rating-repo-user-22")
    liker = await _make_user(db, "rating-repo-user-23")

    rating = await upsert_rating(
        db, user_id=author, item_type="MOVIE", item_id=movie.id, score=5, review_text="Great"
    )
    await create_like_if_not_exists(db, user_id=liker, rating_id=rating.id)

    rows, _ = await list_ratings_for_item(db, "MOVIE", movie.id, page=1, limit=20, caller_id=None)
    _, _, _, liked_by_viewer = rows[0]
    assert liked_by_viewer is False


# ── list_user_reviews (cross-type UNION ALL) ─────────────────────────────


async def test_list_user_reviews_cross_type_union(db):
    user_id = await _make_user(db, "rating-repo-user-10")
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-8"))
    series = await upsert_series(db, _series_data("repo-rating-series-1"))

    await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=5, review_text="Loved it"
    )
    await upsert_rating(
        db,
        user_id=user_id,
        item_type="SERIES",
        item_id=series.id,
        score=None,
        review_text="Text only",
    )

    rows, total = await list_user_reviews(db, user_id, page=1, limit=20)
    assert total == 2
    item_types = {row.item_type for row in rows}
    assert item_types == {"MOVIE", "SERIES"}


async def test_list_user_reviews_excludes_other_users(db):
    user_a = await _make_user(db, "rating-repo-user-11")
    user_b = await _make_user(db, "rating-repo-user-12")
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-9"))

    await upsert_rating(
        db, user_id=user_a, item_type="MOVIE", item_id=movie.id, score=3, review_text=None
    )

    rows, total = await list_user_reviews(db, user_b, page=1, limit=20)
    assert total == 0
    assert rows == []


# ── likes ─────────────────────────────────────────────────────────────────


async def test_create_like_if_not_exists_idempotent(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-10"))
    author_id = await _make_user(db, "rating-repo-user-13")
    liker_id = await _make_user(db, "rating-repo-user-14")

    rating = await upsert_rating(
        db, user_id=author_id, item_type="MOVIE", item_id=movie.id, score=4, review_text="Nice"
    )

    await create_like_if_not_exists(db, user_id=liker_id, rating_id=rating.id)
    await create_like_if_not_exists(db, user_id=liker_id, rating_id=rating.id)

    count = await count_likes(db, rating.id)
    assert count == 1


async def test_delete_like_if_exists_idempotent(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-11"))
    author_id = await _make_user(db, "rating-repo-user-15")
    liker_id = await _make_user(db, "rating-repo-user-16")

    rating = await upsert_rating(
        db, user_id=author_id, item_type="MOVIE", item_id=movie.id, score=4, review_text="Nice"
    )
    await create_like_if_not_exists(db, user_id=liker_id, rating_id=rating.id)

    await delete_like_if_exists(db, user_id=liker_id, rating_id=rating.id)
    # Deleting again must not raise.
    await delete_like_if_exists(db, user_id=liker_id, rating_id=rating.id)

    assert await get_like(db, user_id=liker_id, rating_id=rating.id) is None
    assert await count_likes(db, rating.id) == 0


async def test_get_rating_by_id_found_and_not_found(db):
    movie = await upsert_movie(db, _movie_data("repo-rating-movie-12"))
    user_id = await _make_user(db, "rating-repo-user-17")
    rating = await upsert_rating(
        db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=2, review_text=None
    )

    found = await get_rating_by_id(db, rating.id)
    assert found is not None
    assert found.id == rating.id

    assert await get_rating_by_id(db, 999_999_999) is None
