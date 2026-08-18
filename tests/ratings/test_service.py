"""Service tests for backlogg/ratings/service.py.

No external adapter to mock for this domain — runs against the real test DB.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from backlogg.movies.repository import get_movie_by_slug, upsert_movie
from backlogg.ratings import service
from backlogg.ratings.schemas import RatingIn
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Service Rating Movie") -> dict:
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


# ── rate_item ────────────────────────────────────────────────────────────


async def test_rate_item_creates_and_recalculates_aggregate(db):
    await upsert_movie(db, _movie_data("service-rating-movie-1"))
    user = await _make_user(db, "svc-rating-user-1")

    result = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-1",
        payload=RatingIn(score=5, review_text="Excellent"),
        user=user,
    )

    assert result.score == 5
    assert result.review_text == "Excellent"
    assert result.user.username == "svc-rating-user-1"
    assert result.like_count == 0

    movie = await get_movie_by_slug(db, "service-rating-movie-1")
    assert movie.rating_count_internal == 1
    assert float(movie.rating_internal) == 5.0


async def test_rate_item_accepts_half_star_score_and_recalculates(db):
    await upsert_movie(db, _movie_data("service-rating-movie-11"))
    user = await _make_user(db, "svc-rating-user-20")

    result = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-11",
        payload=RatingIn(score=3.5, review_text="Half star"),
        user=user,
    )

    assert result.score == 3.5

    movie = await get_movie_by_slug(db, "service-rating-movie-11")
    assert float(movie.rating_internal) == 3.5


async def test_rate_item_slug_not_found_raises_404(db):
    user = await _make_user(db, "svc-rating-user-2")

    with pytest.raises(HTTPException) as exc_info:
        await service.rate_item(
            db,
            item_type="MOVIE",
            slug="no-such-movie-service-rating",
            payload=RatingIn(score=3, review_text=None),
            user=user,
        )
    assert exc_info.value.status_code == 404


async def test_rate_item_upsert_replaces_previous_score(db):
    await upsert_movie(db, _movie_data("service-rating-movie-2"))
    user = await _make_user(db, "svc-rating-user-3")

    await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-2",
        payload=RatingIn(score=2, review_text="Meh"),
        user=user,
    )
    result = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-2",
        payload=RatingIn(score=4, review_text="Better on rewatch"),
        user=user,
    )

    assert result.score == 4
    assert result.review_text == "Better on rewatch"

    movie = await get_movie_by_slug(db, "service-rating-movie-2")
    assert movie.rating_count_internal == 1
    assert float(movie.rating_internal) == 4.0


# ── delete_item_rating ──────────────────────────────────────────────────


async def test_delete_item_rating_removes_and_recalculates(db):
    await upsert_movie(db, _movie_data("service-rating-movie-3"))
    user = await _make_user(db, "svc-rating-user-4")

    await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-3",
        payload=RatingIn(score=3, review_text=None),
        user=user,
    )
    await service.delete_item_rating(
        db, item_type="MOVIE", slug="service-rating-movie-3", user=user
    )

    movie = await get_movie_by_slug(db, "service-rating-movie-3")
    assert movie.rating_count_internal == 0
    assert movie.rating_internal is None


async def test_delete_item_rating_not_found_raises_404(db):
    await upsert_movie(db, _movie_data("service-rating-movie-4"))
    user = await _make_user(db, "svc-rating-user-5")

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_item_rating(
            db, item_type="MOVIE", slug="service-rating-movie-4", user=user
        )
    assert exc_info.value.status_code == 404


async def test_delete_item_rating_slug_not_found_raises_404(db):
    user = await _make_user(db, "svc-rating-user-6")

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_item_rating(
            db, item_type="MOVIE", slug="no-such-movie-delete-rating", user=user
        )
    assert exc_info.value.status_code == 404


# ── list_item_ratings ────────────────────────────────────────────────────


async def test_list_item_ratings_includes_like_count(db):
    await upsert_movie(db, _movie_data("service-rating-movie-5"))
    author = await _make_user(db, "svc-rating-user-7")
    liker = await _make_user(db, "svc-rating-user-8")

    await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-5",
        payload=RatingIn(score=5, review_text="Loved it"),
        user=author,
    )
    rating = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-5",
        payload=RatingIn(score=4, review_text="Also good"),
        user=liker,
    )
    await service.like_review(db, rating_id=rating.id, user=liker)

    result = await service.list_item_ratings(
        db, item_type="MOVIE", slug="service-rating-movie-5", page=1, limit=20
    )
    assert result.total == 2
    liked_entry = next(r for r in result.items if r.id == rating.id)
    assert liked_entry.like_count == 1


async def test_list_item_ratings_liked_by_viewer_reflects_caller(db):
    await upsert_movie(db, _movie_data("service-rating-movie-10"))
    author = await _make_user(db, "svc-rating-user-17")
    liker = await _make_user(db, "svc-rating-user-18")
    stranger = await _make_user(db, "svc-rating-user-19")

    rating = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-10",
        payload=RatingIn(score=5, review_text="Loved it"),
        user=author,
    )
    await service.like_review(db, rating_id=rating.id, user=liker)

    liker_view = await service.list_item_ratings(
        db, item_type="MOVIE", slug="service-rating-movie-10", page=1, limit=20, caller_id=liker.id
    )
    assert next(r for r in liker_view.items if r.id == rating.id).liked_by_viewer is True

    stranger_view = await service.list_item_ratings(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-10",
        page=1,
        limit=20,
        caller_id=stranger.id,
    )
    assert next(r for r in stranger_view.items if r.id == rating.id).liked_by_viewer is False

    anonymous_view = await service.list_item_ratings(
        db, item_type="MOVIE", slug="service-rating-movie-10", page=1, limit=20
    )
    assert next(r for r in anonymous_view.items if r.id == rating.id).liked_by_viewer is False


async def test_list_item_ratings_slug_not_found_raises_404(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.list_item_ratings(
            db, item_type="MOVIE", slug="no-such-movie-list-ratings", page=1, limit=20
        )
    assert exc_info.value.status_code == 404


# ── like_review / unlike_review ─────────────────────────────────────────


async def test_like_review_idempotent(db):
    await upsert_movie(db, _movie_data("service-rating-movie-6"))
    author = await _make_user(db, "svc-rating-user-9")
    liker = await _make_user(db, "svc-rating-user-10")

    rating = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-6",
        payload=RatingIn(score=5, review_text="Nice"),
        user=author,
    )

    await service.like_review(db, rating_id=rating.id, user=liker)
    await service.like_review(db, rating_id=rating.id, user=liker)

    from backlogg.ratings.repository import count_likes

    assert await count_likes(db, rating.id) == 1


async def test_like_review_rating_not_found_raises_404(db):
    user = await _make_user(db, "svc-rating-user-11")

    with pytest.raises(HTTPException) as exc_info:
        await service.like_review(db, rating_id=999_999_999, user=user)
    assert exc_info.value.status_code == 404


async def test_unlike_review_idempotent(db):
    await upsert_movie(db, _movie_data("service-rating-movie-7"))
    author = await _make_user(db, "svc-rating-user-12")
    liker = await _make_user(db, "svc-rating-user-13")

    rating = await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-7",
        payload=RatingIn(score=5, review_text="Nice"),
        user=author,
    )
    await service.like_review(db, rating_id=rating.id, user=liker)

    await service.unlike_review(db, rating_id=rating.id, user=liker)
    # Unliking again (already unliked) must not raise.
    await service.unlike_review(db, rating_id=rating.id, user=liker)

    from backlogg.ratings.repository import count_likes

    assert await count_likes(db, rating.id) == 0


async def test_unlike_review_rating_not_found_raises_404(db):
    user = await _make_user(db, "svc-rating-user-14")

    with pytest.raises(HTTPException) as exc_info:
        await service.unlike_review(db, rating_id=999_999_998, user=user)
    assert exc_info.value.status_code == 404


# ── get_user_reviews ─────────────────────────────────────────────────────


async def test_get_user_reviews_cross_type(db):
    await upsert_movie(db, _movie_data("service-rating-movie-8"))
    user = await _make_user(db, "svc-rating-user-15")

    await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-8",
        payload=RatingIn(score=5, review_text="Loved it"),
        user=user,
    )

    result = await service.get_user_reviews(db, username="svc-rating-user-15", page=1, limit=20)
    assert result.total == 1
    assert result.items[0].item.item_type == "MOVIE"
    assert result.items[0].item.slug == "service-rating-movie-8"


async def test_get_user_reviews_user_not_found_raises_404(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.get_user_reviews(
            db, username="nobody-has-this-username-reviews", page=1, limit=20
        )
    assert exc_info.value.status_code == 404


async def test_get_user_reviews_includes_text_only_reviews(db):
    await upsert_movie(db, _movie_data("service-rating-movie-9"))
    user = await _make_user(db, "svc-rating-user-16")

    await service.rate_item(
        db,
        item_type="MOVIE",
        slug="service-rating-movie-9",
        payload=RatingIn(score=None, review_text="Text only, no score"),
        user=user,
    )

    result = await service.get_user_reviews(db, username="svc-rating-user-16", page=1, limit=20)
    assert result.total == 1
    assert result.items[0].score is None
    assert result.items[0].review_text == "Text only, no score"
