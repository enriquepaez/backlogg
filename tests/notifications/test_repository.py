"""Repository tests for backlogg/notifications/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
"""

from datetime import UTC, datetime

from backlogg.books.repository import upsert_book
from backlogg.games.repository import upsert_game
from backlogg.movies.repository import upsert_movie
from backlogg.notifications.repository import (
    count_unread,
    create_notification,
    delete_notification,
    list_notifications,
    mark_read,
)
from backlogg.ratings.repository import upsert_rating
from backlogg.series.repository import upsert_series
from backlogg.users.repository import create_user


async def _make_user(db, username: str) -> int:
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
            "avatar_url": f"https://img/{username}.png",
        },
    )
    return user.id


def _movie_data(slug: str) -> dict:
    return {
        "title": "Notif Target Movie",
        "original_title": "Notif Target Movie",
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


def _series_data(slug: str) -> dict:
    return {
        "title": "Notif Target Series",
        "original_title": "Notif Target Series",
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


def _book_data(slug: str) -> dict:
    return {
        "title": "Notif Target Book",
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_data(slug: str) -> dict:
    return {
        "title": "Notif Target Game",
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "release_date": None,
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


# ── create_notification ──────────────────────────────────────────────────


async def test_create_notification_new_follower(db):
    recipient = await _make_user(db, "notif-repo-recip-1")
    actor = await _make_user(db, "notif-repo-actor-1")

    n = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    assert n.id is not None
    assert n.is_read is False
    assert n.type == "new_follower"
    assert n.target_type is None
    assert await count_unread(db, recipient) == 1


async def test_create_notification_review_like_with_target(db):
    recipient = await _make_user(db, "notif-repo-recip-2")
    actor = await _make_user(db, "notif-repo-actor-2")

    n = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=999,
    )

    assert n.type == "review_like"
    assert n.target_type == "review"
    assert n.target_id == 999


# ── list_notifications ───────────────────────────────────────────────────


async def test_list_notifications_reverse_chrono_with_actor_fields(db):
    recipient = await _make_user(db, "notif-repo-recip-3")
    actor1 = await _make_user(db, "notif-repo-actor-3a")
    actor2 = await _make_user(db, "notif-repo-actor-3b")

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor1,
        type="new_follower",
        target_type=None,
        target_id=None,
    )
    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor2,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    rows, total = await list_notifications(db, recipient, page=1, limit=20)
    assert total == 2
    # Newest first — actor2 was written last.
    assert rows[0].username == "notif-repo-actor-3b"
    assert rows[0].display_name == "notif-repo-actor-3b"
    assert rows[0].avatar_url == "https://img/notif-repo-actor-3b.png"
    assert rows[1].username == "notif-repo-actor-3a"


async def test_list_notifications_pagination_and_scoping(db):
    recipient = await _make_user(db, "notif-repo-recip-4")
    other = await _make_user(db, "notif-repo-other-4")
    actor = await _make_user(db, "notif-repo-actor-4")

    for _ in range(3):
        await create_notification(
            db,
            recipient_id=recipient,
            actor_id=actor,
            type="new_follower",
            target_type=None,
            target_id=None,
        )
    # A notification for someone else must not leak.
    await create_notification(
        db,
        recipient_id=other,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    rows_page1, total = await list_notifications(db, recipient, page=1, limit=2)
    assert total == 3
    assert len(rows_page1) == 2

    rows_page2, _ = await list_notifications(db, recipient, page=2, limit=2)
    assert len(rows_page2) == 1


# ── count_unread / mark_read ─────────────────────────────────────────────


async def test_mark_read_all(db):
    recipient = await _make_user(db, "notif-repo-recip-5")
    actor = await _make_user(db, "notif-repo-actor-5")
    for _ in range(2):
        await create_notification(
            db,
            recipient_id=recipient,
            actor_id=actor,
            type="new_follower",
            target_type=None,
            target_id=None,
        )

    assert await count_unread(db, recipient) == 2
    await mark_read(db, recipient, ids=None)
    assert await count_unread(db, recipient) == 0


async def test_mark_read_specific_ids(db):
    recipient = await _make_user(db, "notif-repo-recip-6")
    actor = await _make_user(db, "notif-repo-actor-6")
    n1 = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )
    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    await mark_read(db, recipient, ids=[n1.id])
    assert await count_unread(db, recipient) == 1


async def test_mark_read_idempotent(db):
    recipient = await _make_user(db, "notif-repo-recip-7")
    actor = await _make_user(db, "notif-repo-actor-7")
    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    await mark_read(db, recipient, ids=None)
    await mark_read(db, recipient, ids=None)
    assert await count_unread(db, recipient) == 0


async def test_mark_read_cannot_touch_other_users_notifications(db):
    recipient = await _make_user(db, "notif-repo-recip-8")
    other = await _make_user(db, "notif-repo-other-8")
    actor = await _make_user(db, "notif-repo-actor-8")
    n = await create_notification(
        db,
        recipient_id=other,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    # recipient tries to mark other's notification id — no-op.
    await mark_read(db, recipient, ids=[n.id])
    assert await count_unread(db, other) == 1


# ── target resolution (item_type/slug) ───────────────────────────────────


async def test_list_notifications_new_follower_has_null_target(db):
    recipient = await _make_user(db, "notif-repo-recip-9")
    actor = await _make_user(db, "notif-repo-actor-9")
    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type is None
    assert rows[0].resolved_slug is None


async def test_list_notifications_review_like_resolves_movie_target(db):
    recipient = await _make_user(db, "notif-repo-recip-10")
    actor = await _make_user(db, "notif-repo-actor-10")
    movie = await upsert_movie(db, _movie_data("notif-repo-target-movie-1"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="MOVIE",
        item_id=movie.id,
        score=5,
        review_text="great",
    )

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "MOVIE"
    assert rows[0].resolved_slug == "notif-repo-target-movie-1"


async def test_list_notifications_review_like_resolves_series_target(db):
    recipient = await _make_user(db, "notif-repo-recip-11")
    actor = await _make_user(db, "notif-repo-actor-11")
    series = await upsert_series(db, _series_data("notif-repo-target-series-1"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="SERIES",
        item_id=series.id,
        score=4,
        review_text="good",
    )

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "SERIES"
    assert rows[0].resolved_slug == "notif-repo-target-series-1"


async def test_list_notifications_review_like_resolves_book_target(db):
    recipient = await _make_user(db, "notif-repo-recip-12")
    actor = await _make_user(db, "notif-repo-actor-12")
    book = await upsert_book(db, _book_data("notif-repo-target-book-1"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="BOOK",
        item_id=book.id,
        score=3,
        review_text="ok",
    )

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "BOOK"
    assert rows[0].resolved_slug == "notif-repo-target-book-1"


async def test_list_notifications_review_like_resolves_game_target(db):
    recipient = await _make_user(db, "notif-repo-recip-13")
    actor = await _make_user(db, "notif-repo-actor-13")
    game = await upsert_game(db, _game_data("notif-repo-target-game-1"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="GAME",
        item_id=game.id,
        score=2,
        review_text="meh",
    )

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "GAME"
    assert rows[0].resolved_slug == "notif-repo-target-game-1"


# ── delete_notification ──────────────────────────────────────────────────


async def test_delete_notification_own_returns_true_and_removes_it(db):
    recipient = await _make_user(db, "notif-repo-recip-15")
    actor = await _make_user(db, "notif-repo-actor-15")
    n = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    deleted = await delete_notification(db, recipient, n.id)
    assert deleted is True

    rows, total = await list_notifications(db, recipient, page=1, limit=20)
    assert total == 0
    assert rows == []


async def test_delete_notification_of_another_user_returns_false_and_keeps_it(db):
    recipient = await _make_user(db, "notif-repo-recip-16")
    other = await _make_user(db, "notif-repo-other-16")
    actor = await _make_user(db, "notif-repo-actor-16")
    n = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="new_follower",
        target_type=None,
        target_id=None,
    )

    deleted = await delete_notification(db, other, n.id)
    assert deleted is False

    rows, total = await list_notifications(db, recipient, page=1, limit=20)
    assert total == 1
    assert rows[0].id == n.id


async def test_delete_notification_nonexistent_id_returns_false(db):
    recipient = await _make_user(db, "notif-repo-recip-17")

    deleted = await delete_notification(db, recipient, 999_999_999)
    assert deleted is False


async def test_create_notification_user_completed_with_direct_target(db):
    recipient = await _make_user(db, "notif-repo-recip-18")
    actor = await _make_user(db, "notif-repo-actor-18")
    movie = await upsert_movie(db, _movie_data("notif-repo-target-movie-3"))

    n = await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="user_completed",
        target_type="MOVIE",
        target_id=movie.id,
    )

    assert n.type == "user_completed"
    assert n.target_type == "MOVIE"
    assert n.target_id == movie.id


async def test_list_notifications_user_completed_resolves_movie_target(db):
    recipient = await _make_user(db, "notif-repo-recip-19")
    actor = await _make_user(db, "notif-repo-actor-19")
    movie = await upsert_movie(db, _movie_data("notif-repo-target-movie-4"))

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="user_completed",
        target_type="MOVIE",
        target_id=movie.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "MOVIE"
    assert rows[0].resolved_slug == "notif-repo-target-movie-4"


async def test_list_notifications_user_completed_resolves_game_target(db):
    recipient = await _make_user(db, "notif-repo-recip-20")
    actor = await _make_user(db, "notif-repo-actor-20")
    game = await upsert_game(db, _game_data("notif-repo-target-game-2"))

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="user_completed",
        target_type="GAME",
        target_id=game.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "GAME"
    assert rows[0].resolved_slug == "notif-repo-target-game-2"


async def test_list_notifications_mixed_review_like_and_user_completed(db):
    """Both target flavors resolve correctly in the same result set."""
    recipient = await _make_user(db, "notif-repo-recip-21")
    actor = await _make_user(db, "notif-repo-actor-21")
    movie = await upsert_movie(db, _movie_data("notif-repo-target-movie-5"))
    series = await upsert_series(db, _series_data("notif-repo-target-series-2"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="SERIES",
        item_id=series.id,
        score=5,
        review_text="great",
    )

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )
    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="user_completed",
        target_type="MOVIE",
        target_id=movie.id,
    )

    rows, total = await list_notifications(db, recipient, page=1, limit=20)
    assert total == 2
    by_type = {row.type: row for row in rows}
    assert by_type["review_like"].resolved_item_type == "SERIES"
    assert by_type["review_like"].resolved_slug == "notif-repo-target-series-2"
    assert by_type["user_completed"].resolved_item_type == "MOVIE"
    assert by_type["user_completed"].resolved_slug == "notif-repo-target-movie-5"


async def test_list_notifications_review_like_target_resolved_even_when_hidden(db):
    """A hidden review still resolves its item target — the link is to the
    item's page, not to the review itself, so moderation doesn't affect it."""
    recipient = await _make_user(db, "notif-repo-recip-14")
    actor = await _make_user(db, "notif-repo-actor-14")
    movie = await upsert_movie(db, _movie_data("notif-repo-target-movie-2"))
    rating = await upsert_rating(
        db,
        user_id=recipient,
        item_type="MOVIE",
        item_id=movie.id,
        score=5,
        review_text="great",
    )
    rating.is_hidden = True
    await db.flush()

    await create_notification(
        db,
        recipient_id=recipient,
        actor_id=actor,
        type="review_like",
        target_type="review",
        target_id=rating.id,
    )

    rows, _ = await list_notifications(db, recipient, page=1, limit=20)
    assert rows[0].resolved_item_type == "MOVIE"
    assert rows[0].resolved_slug == "notif-repo-target-movie-2"
