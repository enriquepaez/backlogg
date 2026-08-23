"""Service tests for notification generation wired into follows/ratings.

Covers: generation on follow and on like, no self-notification, no duplication
on idempotent re-follow/re-like, and graceful degradation (a notification
failure must not break the source operation). Runs against the real test DB.
"""

from datetime import UTC, datetime

from backlogg.follows import service as follows_service
from backlogg.follows.repository import count_following
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryStatus
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


# ── generation on status_completed (feature 55) ──────────────────────────


async def test_complete_item_notifies_direct_follower(db):
    completer = await _make_user(db, "notif-svc-completer-1")
    follower = await _make_user(db, "notif-svc-completer-follower-1")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-1"))
    await follows_service.follow_user(db, username="notif-svc-completer-1", user=follower)

    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-1", LibraryStatus.completed, completer
    )

    rows, total = await notif_repo.list_notifications(db, follower.id, page=1, limit=20)
    assert total == 1
    assert rows[0].type == "user_completed"
    assert rows[0].username == "notif-svc-completer-1"
    assert rows[0].target_type == "MOVIE"


async def test_complete_item_does_not_notify_followers_of_followers(db):
    completer = await _make_user(db, "notif-svc-completer-2")
    direct_follower = await _make_user(db, "notif-svc-completer-follower-2")
    indirect_follower = await _make_user(db, "notif-svc-completer-follower-2b")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-2"))

    # indirect_follower follows direct_follower, not the completer — must not
    # be notified (no fan-out beyond direct followers).
    await follows_service.follow_user(db, username="notif-svc-completer-2", user=direct_follower)
    await follows_service.follow_user(
        db, username="notif-svc-completer-follower-2", user=indirect_follower
    )

    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-2", LibraryStatus.completed, completer
    )

    # direct_follower also has an (unrelated) new_follower notification from
    # indirect_follower following them — assert on user_completed specifically.
    direct_rows, _ = await notif_repo.list_notifications(db, direct_follower.id, page=1, limit=20)
    assert [r.type for r in direct_rows if r.type == "user_completed"] == ["user_completed"]

    indirect_rows, _ = await notif_repo.list_notifications(
        db, indirect_follower.id, page=1, limit=20
    )
    assert all(r.type != "user_completed" for r in indirect_rows)


async def test_complete_item_does_not_notify_non_followers(db):
    completer = await _make_user(db, "notif-svc-completer-3")
    stranger = await _make_user(db, "notif-svc-stranger-3")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-3"))

    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-3", LibraryStatus.completed, completer
    )

    assert await notif_repo.count_unread(db, stranger.id) == 0


async def test_repeat_completion_generates_new_notification_each_time(db):
    completer = await _make_user(db, "notif-svc-completer-4")
    follower = await _make_user(db, "notif-svc-completer-follower-4")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-4"))
    await follows_service.follow_user(db, username="notif-svc-completer-4", user=follower)

    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-4", LibraryStatus.completed, completer
    )
    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-4", LibraryStatus.dropped, completer
    )
    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-4", LibraryStatus.completed, completer
    )

    rows, total = await notif_repo.list_notifications(db, follower.id, page=1, limit=20)
    assert total == 2
    assert all(row.type == "user_completed" for row in rows)


async def test_repeat_completed_put_does_not_duplicate_notification(db):
    completer = await _make_user(db, "notif-svc-completer-5")
    follower = await _make_user(db, "notif-svc-completer-follower-5")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-5"))
    await follows_service.follow_user(db, username="notif-svc-completer-5", user=follower)

    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-5", LibraryStatus.completed, completer
    )
    # Re-PUTting the same status is a no-op transition — must not duplicate.
    await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-5", LibraryStatus.completed, completer
    )

    assert await notif_repo.count_unread(db, follower.id) == 1


async def test_complete_item_graceful_degradation(db, monkeypatch):
    completer = await _make_user(db, "notif-svc-completer-6")
    follower = await _make_user(db, "notif-svc-completer-follower-6")
    await upsert_movie(db, _movie_data("notif-svc-completed-movie-6"))
    await follows_service.follow_user(db, username="notif-svc-completer-6", user=follower)

    async def boom(*args, **kwargs):
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notif_repo, "create_user_completed_notifications_for_followers", boom)

    # Notification generation fails, but the library status write must still
    # persist and the call must not raise.
    out = await library_service.set_library_status(
        db, "MOVIE", "notif-svc-completed-movie-6", LibraryStatus.completed, completer
    )
    assert out.status == "completed"


# ── batched fan-out (feature 57) ─────────────────────────────────────────


async def _completion_execute_call_count(
    db, *, follower_count: int, suffix: str
) -> tuple[int, list]:
    """Run a fresh completion with ``follower_count`` direct followers.

    Returns how many ``AsyncSession.execute`` calls it took end to end, plus
    the follower users, so callers can also assert on correctness.
    """
    completer = await _make_user(db, f"notif-svc-completer-fanout-{suffix}")
    followers = []
    for i in range(follower_count):
        follower = await _make_user(db, f"notif-svc-completer-follower-fanout-{suffix}-{i}")
        await follows_service.follow_user(
            db, username=f"notif-svc-completer-fanout-{suffix}", user=follower
        )
        followers.append(follower)
    await upsert_movie(db, _movie_data(f"notif-svc-completed-movie-fanout-{suffix}"))

    calls = 0
    original_execute = db.execute

    async def counting_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original_execute(*args, **kwargs)

    db.execute = counting_execute
    try:
        await library_service.set_library_status(
            db,
            "MOVIE",
            f"notif-svc-completed-movie-fanout-{suffix}",
            LibraryStatus.completed,
            completer,
        )
    finally:
        db.execute = original_execute
    return calls, followers


async def test_complete_item_fanout_does_not_scale_with_follower_count(db):
    """The whole set_library_status call (status write + feed event + the
    user_completed fan-out) must emit the same number of queries whether the
    completer has 2 or 25 direct followers — the fan-out is one batched
    INSERT ... SELECT, not one INSERT per follower."""
    few_calls, _ = await _completion_execute_call_count(db, follower_count=2, suffix="few")
    many_calls, many_followers = await _completion_execute_call_count(
        db, follower_count=25, suffix="many"
    )

    assert few_calls == many_calls

    # Correctness: the batched insert must still have reached every follower.
    for follower in many_followers:
        assert await notif_repo.count_unread(db, follower.id) == 1


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
