"""Repository tests for backlogg/notifications/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
"""

from backlogg.notifications.repository import (
    count_unread,
    create_notification,
    list_notifications,
    mark_read,
)
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
