from backlogg.users.repository import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    update_user,
)


def _user_data(username: str, email: str) -> dict:
    return {
        "username": username,
        "email": email,
        "password_hash": "argon2-hash-placeholder",
        "display_name": "Test User",
    }


async def test_create_user(db):
    """Creating a user persists all provided fields and generates an id."""
    user = await create_user(db, _user_data("repo-user-1", "repo-user-1@example.com"))

    assert user.id is not None
    assert user.username == "repo-user-1"
    assert user.email == "repo-user-1@example.com"
    assert user.password_hash == "argon2-hash-placeholder"
    assert user.display_name == "Test User"
    assert user.bio is None
    assert user.avatar_url is None


async def test_get_user_by_username_found(db):
    """Looking up an existing username returns the User."""
    await create_user(db, _user_data("repo-user-2", "repo-user-2@example.com"))

    user = await get_user_by_username(db, "repo-user-2")
    assert user is not None
    assert user.email == "repo-user-2@example.com"


async def test_get_user_by_username_not_found(db):
    """Looking up a non-existent username returns None."""
    user = await get_user_by_username(db, "does-not-exist-repo-user")
    assert user is None


async def test_get_user_by_email_found(db):
    """Looking up an existing email returns the User."""
    await create_user(db, _user_data("repo-user-3", "repo-user-3@example.com"))

    user = await get_user_by_email(db, "repo-user-3@example.com")
    assert user is not None
    assert user.username == "repo-user-3"


async def test_get_user_by_email_not_found(db):
    """Looking up a non-existent email returns None."""
    user = await get_user_by_email(db, "nobody-repo-user@example.com")
    assert user is None


async def test_get_user_by_id(db):
    """Looking up by primary key returns the matching User."""
    created = await create_user(db, _user_data("repo-user-4", "repo-user-4@example.com"))

    user = await get_user_by_id(db, created.id)
    assert user is not None
    assert user.username == "repo-user-4"


async def test_get_user_by_id_not_found(db):
    """Looking up a non-existent id returns None."""
    user = await get_user_by_id(db, 9_999_999)
    assert user is None


async def test_update_user(db):
    """update_user applies only the given fields."""
    created = await create_user(db, _user_data("repo-user-5", "repo-user-5@example.com"))

    updated = await update_user(
        db,
        created,
        {"display_name": "New Name", "bio": "A short bio", "avatar_url": "https://ex.com/a.png"},
    )

    assert updated.display_name == "New Name"
    assert updated.bio == "A short bio"
    assert updated.avatar_url == "https://ex.com/a.png"
    # Untouched fields remain unchanged
    assert updated.username == "repo-user-5"
    assert updated.email == "repo-user-5@example.com"
