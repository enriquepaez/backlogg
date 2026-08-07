"""Repository tests for backlogg/follows/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
"""

from backlogg.follows.repository import (
    count_followers,
    count_following,
    create_follow_if_not_exists,
    delete_follow_if_exists,
    list_followers,
    list_following,
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
        },
    )
    return user.id


# ── create_follow_if_not_exists ──────────────────────────────────────────


async def test_create_follow_creates_relationship(db):
    a = await _make_user(db, "follow-repo-user-1")
    b = await _make_user(db, "follow-repo-user-2")

    await create_follow_if_not_exists(db, follower_id=a, followed_id=b)

    assert await count_following(db, a) == 1
    assert await count_followers(db, b) == 1


async def test_create_follow_idempotent(db):
    a = await _make_user(db, "follow-repo-user-3")
    b = await _make_user(db, "follow-repo-user-4")

    await create_follow_if_not_exists(db, follower_id=a, followed_id=b)
    await create_follow_if_not_exists(db, follower_id=a, followed_id=b)

    assert await count_following(db, a) == 1
    assert await count_followers(db, b) == 1


# ── delete_follow_if_exists ──────────────────────────────────────────────


async def test_delete_follow_removes_relationship(db):
    a = await _make_user(db, "follow-repo-user-5")
    b = await _make_user(db, "follow-repo-user-6")

    await create_follow_if_not_exists(db, follower_id=a, followed_id=b)
    await delete_follow_if_exists(db, follower_id=a, followed_id=b)

    assert await count_following(db, a) == 0
    assert await count_followers(db, b) == 0


async def test_delete_follow_idempotent_when_not_following(db):
    a = await _make_user(db, "follow-repo-user-7")
    b = await _make_user(db, "follow-repo-user-8")

    # Never followed — deleting must not raise.
    await delete_follow_if_exists(db, follower_id=a, followed_id=b)
    await delete_follow_if_exists(db, follower_id=a, followed_id=b)

    assert await count_following(db, a) == 0


# ── counts ────────────────────────────────────────────────────────────────


async def test_counts_reflect_multiple_relationships(db):
    target = await _make_user(db, "follow-repo-target")
    f1 = await _make_user(db, "follow-repo-f1")
    f2 = await _make_user(db, "follow-repo-f2")

    await create_follow_if_not_exists(db, follower_id=f1, followed_id=target)
    await create_follow_if_not_exists(db, follower_id=f2, followed_id=target)
    await create_follow_if_not_exists(db, follower_id=target, followed_id=f1)

    assert await count_followers(db, target) == 2
    assert await count_following(db, target) == 1


# ── list_followers / list_following (pagination) ─────────────────────────


async def test_list_followers_pagination(db):
    target = await _make_user(db, "follow-repo-list-target")
    f1 = await _make_user(db, "follow-repo-list-f1")
    f2 = await _make_user(db, "follow-repo-list-f2")

    await create_follow_if_not_exists(db, follower_id=f1, followed_id=target)
    await create_follow_if_not_exists(db, follower_id=f2, followed_id=target)

    rows_page1, total = await list_followers(db, target, page=1, limit=1)
    assert total == 2
    assert len(rows_page1) == 1
    # Most recent first — f2 was written last.
    assert rows_page1[0].id == f2

    rows_page2, _ = await list_followers(db, target, page=2, limit=1)
    assert rows_page2[0].id == f1


async def test_list_following_pagination(db):
    follower = await _make_user(db, "follow-repo-following-src")
    t1 = await _make_user(db, "follow-repo-following-t1")
    t2 = await _make_user(db, "follow-repo-following-t2")

    await create_follow_if_not_exists(db, follower_id=follower, followed_id=t1)
    await create_follow_if_not_exists(db, follower_id=follower, followed_id=t2)

    rows, total = await list_following(db, follower, page=1, limit=20)
    assert total == 2
    ids = {u.id for u in rows}
    assert ids == {t1, t2}


async def test_list_followers_empty(db):
    lonely = await _make_user(db, "follow-repo-lonely")
    rows, total = await list_followers(db, lonely, page=1, limit=20)
    assert total == 0
    assert rows == []
