"""Service tests for backlogg/follows/service.py.

No external adapter to mock for this domain — runs against the real test DB.
"""

import pytest
from fastapi import HTTPException

from backlogg.follows import service
from backlogg.follows.repository import count_followers, count_following
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


# ── follow_user ──────────────────────────────────────────────────────────


async def test_follow_user_creates_relationship(db):
    follower = await _make_user(db, "svc-follow-user-1")
    target = await _make_user(db, "svc-follow-target-1")

    await service.follow_user(db, username="svc-follow-target-1", user=follower)

    assert await count_following(db, follower.id) == 1
    assert await count_followers(db, target.id) == 1


async def test_follow_user_idempotent(db):
    follower = await _make_user(db, "svc-follow-user-2")
    await _make_user(db, "svc-follow-target-2")

    await service.follow_user(db, username="svc-follow-target-2", user=follower)
    await service.follow_user(db, username="svc-follow-target-2", user=follower)

    assert await count_following(db, follower.id) == 1


async def test_follow_self_raises_422(db):
    user = await _make_user(db, "svc-follow-self")

    with pytest.raises(HTTPException) as exc_info:
        await service.follow_user(db, username="svc-follow-self", user=user)
    assert exc_info.value.status_code == 422


async def test_follow_unknown_username_raises_404(db):
    follower = await _make_user(db, "svc-follow-user-3")

    with pytest.raises(HTTPException) as exc_info:
        await service.follow_user(db, username="nobody-has-this-username-follow", user=follower)
    assert exc_info.value.status_code == 404


# ── unfollow_user ────────────────────────────────────────────────────────


async def test_unfollow_user_removes_relationship(db):
    follower = await _make_user(db, "svc-unfollow-user-1")
    target = await _make_user(db, "svc-unfollow-target-1")

    await service.follow_user(db, username="svc-unfollow-target-1", user=follower)
    await service.unfollow_user(db, username="svc-unfollow-target-1", user=follower)

    assert await count_following(db, follower.id) == 0
    assert await count_followers(db, target.id) == 0


async def test_unfollow_tolerant_when_not_following(db):
    follower = await _make_user(db, "svc-unfollow-user-2")
    await _make_user(db, "svc-unfollow-target-2")

    # Never followed — unfollowing must not raise.
    await service.unfollow_user(db, username="svc-unfollow-target-2", user=follower)
    await service.unfollow_user(db, username="svc-unfollow-target-2", user=follower)

    assert await count_following(db, follower.id) == 0


async def test_unfollow_unknown_username_raises_404(db):
    follower = await _make_user(db, "svc-unfollow-user-3")

    with pytest.raises(HTTPException) as exc_info:
        await service.unfollow_user(db, username="nobody-has-this-username-unfollow", user=follower)
    assert exc_info.value.status_code == 404


# ── list_followers / list_following ──────────────────────────────────────


async def test_list_followers_returns_paginated(db):
    await _make_user(db, "svc-list-target")
    f1 = await _make_user(db, "svc-list-f1")
    f2 = await _make_user(db, "svc-list-f2")

    await service.follow_user(db, username="svc-list-target", user=f1)
    await service.follow_user(db, username="svc-list-target", user=f2)

    result = await service.list_followers(db, username="svc-list-target", page=1, limit=20)
    assert result.total == 2
    usernames = {item.username for item in result.items}
    assert usernames == {"svc-list-f1", "svc-list-f2"}


async def test_list_following_returns_paginated(db):
    follower = await _make_user(db, "svc-list-following-src")
    await _make_user(db, "svc-list-following-t1")
    await _make_user(db, "svc-list-following-t2")

    await service.follow_user(db, username="svc-list-following-t1", user=follower)
    await service.follow_user(db, username="svc-list-following-t2", user=follower)

    result = await service.list_following(db, username="svc-list-following-src", page=1, limit=20)
    assert result.total == 2
    usernames = {item.username for item in result.items}
    assert usernames == {"svc-list-following-t1", "svc-list-following-t2"}


async def test_list_followers_unknown_username_raises_404(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.list_followers(
            db, username="nobody-has-this-username-followers", page=1, limit=20
        )
    assert exc_info.value.status_code == 404


async def test_list_following_unknown_username_raises_404(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.list_following(
            db, username="nobody-has-this-username-following", page=1, limit=20
        )
    assert exc_info.value.status_code == 404
