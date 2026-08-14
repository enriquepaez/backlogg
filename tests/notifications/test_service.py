"""Service tests for notification generation wired into follows/ratings.

Covers: generation on follow and on like, no self-notification, no duplication
on idempotent re-follow/re-like, and graceful degradation (a notification
failure must not break the source operation). Runs against the real test DB.
"""

from datetime import UTC, datetime

from backlogg.follows import service as follows_service
from backlogg.follows.repository import count_following
from backlogg.movies.repository import upsert_movie
from backlogg.notifications import repository as notif_repo
from backlogg.notifications import service as notif_service
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn
from backlogg.users.repository import create_user


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


def _movie_data(slug: str) -> dict:
    return {
        "title": "Notif Movie",
        "original_title": "Notif Movie",
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


# ── generation on follow ─────────────────────────────────────────────────


async def test_follow_generates_new_follower_notification(db):
    actor = await _make_user(db, "notif-svc-follower-1")
    target = await _make_user(db, "notif-svc-target-1")

    await follows_service.follow_user(db, username="notif-svc-target-1", user=actor)

    rows, total = await notif_repo.list_notifications(db, target.id, page=1, limit=20)
    assert total == 1
    assert rows[0].type == "new_follower"
    assert rows[0].username == "notif-svc-follower-1"


async def test_refollow_does_not_duplicate_notification(db):
    actor = await _make_user(db, "notif-svc-follower-2")
    target = await _make_user(db, "notif-svc-target-2")

    await follows_service.follow_user(db, username="notif-svc-target-2", user=actor)
    # Re-follow is an idempotent no-op — must not create a second notification.
    await follows_service.follow_user(db, username="notif-svc-target-2", user=actor)

    assert await notif_repo.count_unread(db, target.id) == 1


async def test_follow_graceful_degradation(db, monkeypatch):
    actor = await _make_user(db, "notif-svc-follower-3")
    target = await _make_user(db, "notif-svc-target-3")

    async def boom(*args, **kwargs):
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notif_repo, "create_notification", boom)

    # Notification generation fails, but the follow must still persist and the
    # call must not raise.
    await follows_service.follow_user(db, username="notif-svc-target-3", user=actor)

    assert await count_following(db, actor.id) == 1
    assert await notif_repo.count_unread(db, target.id) == 0


# ── generation on like ───────────────────────────────────────────────────


async def _make_review(db, movie_slug: str, author):
    await upsert_movie(db, _movie_data(movie_slug))
    rating = await ratings_service.rate_item(
        db,
        item_type="MOVIE",
        slug=movie_slug,
        payload=RatingIn(score=5, review_text="great"),
        user=author,
    )
    return rating


async def test_like_generates_review_like_notification(db):
    author = await _make_user(db, "notif-svc-author-1")
    liker = await _make_user(db, "notif-svc-liker-1")
    rating = await _make_review(db, "notif-svc-movie-1", author)

    await ratings_service.like_review(db, rating_id=rating.id, user=liker)

    rows, total = await notif_repo.list_notifications(db, author.id, page=1, limit=20)
    assert total == 1
    assert rows[0].type == "review_like"
    assert rows[0].target_type == "review"
    assert rows[0].target_id == rating.id
    assert rows[0].username == "notif-svc-liker-1"


async def test_like_notification_target_resolves_via_service(db):
    """The service maps the resolved item_type/slug onto NotificationTargetOut."""
    author = await _make_user(db, "notif-svc-author-6")
    liker = await _make_user(db, "notif-svc-liker-6")
    rating = await _make_review(db, "notif-svc-movie-6", author)

    await ratings_service.like_review(db, rating_id=rating.id, user=liker)

    result = await notif_service.list_notifications(db, author, page=1, limit=20)
    entry = result.items[0]
    assert entry.type == "review_like"
    assert entry.target.item_type == "MOVIE"
    assert entry.target.slug == "notif-svc-movie-6"


async def test_new_follower_target_item_type_and_slug_are_null(db):
    actor = await _make_user(db, "notif-svc-follower-6")
    target = await _make_user(db, "notif-svc-target-6")

    await follows_service.follow_user(db, username="notif-svc-target-6", user=actor)

    result = await notif_service.list_notifications(db, target, page=1, limit=20)
    entry = result.items[0]
    assert entry.type == "new_follower"
    assert entry.target.item_type is None
    assert entry.target.slug is None


async def test_self_like_does_not_notify(db):
    author = await _make_user(db, "notif-svc-author-2")
    rating = await _make_review(db, "notif-svc-movie-2", author)

    await ratings_service.like_review(db, rating_id=rating.id, user=author)

    assert await notif_repo.count_unread(db, author.id) == 0


async def test_relike_does_not_duplicate_notification(db):
    author = await _make_user(db, "notif-svc-author-3")
    liker = await _make_user(db, "notif-svc-liker-3")
    rating = await _make_review(db, "notif-svc-movie-3", author)

    await ratings_service.like_review(db, rating_id=rating.id, user=liker)
    await ratings_service.like_review(db, rating_id=rating.id, user=liker)

    assert await notif_repo.count_unread(db, author.id) == 1


async def test_unlike_does_not_notify(db):
    author = await _make_user(db, "notif-svc-author-4")
    liker = await _make_user(db, "notif-svc-liker-4")
    rating = await _make_review(db, "notif-svc-movie-4", author)

    await ratings_service.unlike_review(db, rating_id=rating.id, user=liker)

    assert await notif_repo.count_unread(db, author.id) == 0


# ── read side ────────────────────────────────────────────────────────────


async def test_mark_read_service_is_idempotent(db):
    actor = await _make_user(db, "notif-svc-follower-5")
    target = await _make_user(db, "notif-svc-target-5")
    await follows_service.follow_user(db, username="notif-svc-target-5", user=actor)

    await notif_service.mark_read(db, user=target, ids=None)
    await notif_service.mark_read(db, user=target, ids=None)

    result = await notif_service.unread_count(db, user=target)
    assert result.unread_count == 0


# ── delete_notification ─────────────────────────────────────────────────


async def test_delete_notification_own_returns_true(db):
    actor = await _make_user(db, "notif-svc-follower-7")
    target = await _make_user(db, "notif-svc-target-7")
    await follows_service.follow_user(db, username="notif-svc-target-7", user=actor)

    result = await notif_service.list_notifications(db, target, page=1, limit=20)
    notification_id = result.items[0].id

    deleted = await notif_service.delete_notification(db, target, notification_id)
    assert deleted is True

    result_after = await notif_service.list_notifications(db, target, page=1, limit=20)
    assert result_after.total == 0


async def test_delete_notification_of_another_user_returns_false(db):
    actor = await _make_user(db, "notif-svc-follower-8")
    target = await _make_user(db, "notif-svc-target-8")
    other = await _make_user(db, "notif-svc-other-8")
    await follows_service.follow_user(db, username="notif-svc-target-8", user=actor)

    result = await notif_service.list_notifications(db, target, page=1, limit=20)
    notification_id = result.items[0].id

    deleted = await notif_service.delete_notification(db, other, notification_id)
    assert deleted is False

    result_after = await notif_service.list_notifications(db, target, page=1, limit=20)
    assert result_after.total == 1
