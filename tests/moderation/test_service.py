"""Service tests for backlogg/moderation/service.py — ban/unban query batching.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
Covers the acceptance criterion of feature 62: banning/unbanning a user with
many rated items must recompute all of their aggregates without the number of
executed queries scaling with the number of ratings — same pattern as the
notification fan-out batching test in tests/notifications/test_service.py
(feature 57).
"""

from datetime import UTC, datetime

from backlogg.moderation import service as moderation_service
from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import get_item_by_slug, upsert_rating
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Mod Service Movie") -> dict:
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


async def _ban_execute_call_count(db, *, rated_item_count: int, suffix: str, banned: bool) -> int:
    """Ban (or unban) a fresh author who has rated ``rated_item_count`` distinct
    items. Returns how many ``AsyncSession.execute`` calls it took end to end.
    """
    author = await _make_user(db, f"mod-svc-batch-author-{suffix}")
    if banned:
        # Unbanning requires the user to already be banned.
        await moderation_service.set_user_banned(db, author.username, True)

    for i in range(rated_item_count):
        movie = await upsert_movie(db, _movie_data(f"mod-svc-batch-movie-{suffix}-{i}"))
        await upsert_rating(
            db, user_id=author.id, item_type="MOVIE", item_id=movie.id, score=4, review_text=None
        )

    calls = 0
    original_execute = db.execute

    async def counting_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original_execute(*args, **kwargs)

    db.execute = counting_execute
    try:
        await moderation_service.set_user_banned(db, author.username, not banned)
    finally:
        db.execute = original_execute
    return calls


async def test_ban_query_count_does_not_scale_with_rated_item_count(db):
    few_calls = await _ban_execute_call_count(
        db, rated_item_count=2, suffix="ban-few", banned=False
    )
    many_calls = await _ban_execute_call_count(
        db, rated_item_count=25, suffix="ban-many", banned=False
    )

    assert few_calls == many_calls


async def test_unban_query_count_does_not_scale_with_rated_item_count(db):
    few_calls = await _ban_execute_call_count(
        db, rated_item_count=2, suffix="unban-few", banned=True
    )
    many_calls = await _ban_execute_call_count(
        db, rated_item_count=25, suffix="unban-many", banned=True
    )

    assert few_calls == many_calls


async def test_ban_recomputes_aggregates_for_every_rated_item(db):
    author = await _make_user(db, "mod-svc-batch-author-correctness")
    slugs = []
    for i in range(6):
        slug = f"mod-svc-batch-correctness-movie-{i}"
        movie = await upsert_movie(db, _movie_data(slug))
        await upsert_rating(
            db, user_id=author.id, item_type="MOVIE", item_id=movie.id, score=5, review_text=None
        )
        slugs.append(slug)

    await moderation_service.set_user_banned(db, author.username, True)

    for slug in slugs:
        refreshed = await get_item_by_slug(db, "MOVIE", slug)
        assert refreshed.rating_count_internal == 0
        assert refreshed.rating_internal is None

    await moderation_service.set_user_banned(db, author.username, False)

    for slug in slugs:
        refreshed = await get_item_by_slug(db, "MOVIE", slug)
        assert refreshed.rating_count_internal == 1
        assert float(refreshed.rating_internal) == 5.0
