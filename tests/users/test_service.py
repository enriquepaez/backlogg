"""Tests for backlogg/users/service.py — password hashing and account logic.

Runs against the real test DB (no external adapter to mock for this domain).
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException

from backlogg.core.config import settings
from backlogg.users import service
from backlogg.users.auth import create_access_token, get_current_user
from backlogg.users.schemas import UserCreate, UserLogin, UserUpdate

# ── Password hashing ────────────────────────────────────────────────────────


def test_hash_password_does_not_return_plaintext():
    hashed = service.hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert hashed.startswith("$argon2")


def test_verify_password_matches():
    hashed = service.hash_password("correct-horse-battery-staple")
    assert service.verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_password_mismatch():
    hashed = service.hash_password("correct-horse-battery-staple")
    assert service.verify_password("wrong-password", hashed) is False


# ── JWT ──────────────────────────────────────────────────────────────────────


async def test_create_access_token_decodes_to_user_id():
    token = create_access_token(42)
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "42"


async def test_get_current_user_valid_token(db):
    user = await service.register_user(
        db,
        UserCreate(
            username="jwt-user-1",
            email="jwt-user-1@example.com",
            password="s3cret-password",
        ),
    )
    from backlogg.users.repository import get_user_by_username

    persisted = await get_user_by_username(db, user.username)
    token = create_access_token(persisted.id)

    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    resolved = await get_current_user(credentials=credentials, db=db)
    assert resolved.id == persisted.id
    assert resolved.username == "jwt-user-1"


async def test_get_current_user_missing_credentials_raises_401(db):
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None, db=db)
    assert exc_info.value.status_code == 401


async def test_get_current_user_invalid_token_raises_401(db):
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-real-token")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401


async def test_get_current_user_expired_token_raises_401(db):
    from fastapi.security import HTTPAuthorizationCredentials

    now = datetime.now(UTC)
    expired_payload = {
        "sub": "1",
        "iat": now - timedelta(minutes=20),
        "exp": now - timedelta(minutes=10),
    }
    expired_token = jwt.encode(
        expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401


async def test_get_current_user_unknown_user_raises_401(db):
    from fastapi.security import HTTPAuthorizationCredentials

    token = create_access_token(999_999_999)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db)
    assert exc_info.value.status_code == 401


# ── register_user / login_user ────────────────────────────────────────────────


async def test_register_user_persists_hashed_password(db):
    result = await service.register_user(
        db,
        UserCreate(
            username="service-user-1",
            email="service-user-1@example.com",
            password="s3cret-password",
        ),
    )
    assert result.username == "service-user-1"
    assert result.email == "service-user-1@example.com"
    assert not hasattr(result, "password_hash")

    from backlogg.users.repository import get_user_by_username

    persisted = await get_user_by_username(db, "service-user-1")
    assert persisted.password_hash != "s3cret-password"
    assert service.verify_password("s3cret-password", persisted.password_hash)


async def test_register_user_duplicate_username_raises_409(db):
    await service.register_user(
        db,
        UserCreate(
            username="dup-username-user",
            email="dup-username-a@example.com",
            password="s3cret-password",
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.register_user(
            db,
            UserCreate(
                username="dup-username-user",
                email="dup-username-b@example.com",
                password="s3cret-password",
            ),
        )
    assert exc_info.value.status_code == 409


async def test_register_user_duplicate_email_raises_409(db):
    await service.register_user(
        db,
        UserCreate(
            username="dup-email-user-a",
            email="dup-email-user@example.com",
            password="s3cret-password",
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.register_user(
            db,
            UserCreate(
                username="dup-email-user-b",
                email="dup-email-user@example.com",
                password="s3cret-password",
            ),
        )
    assert exc_info.value.status_code == 409


async def test_login_user_success_returns_token(db):
    await service.register_user(
        db,
        UserCreate(
            username="login-user-1",
            email="login-user-1@example.com",
            password="s3cret-password",
        ),
    )
    result = await service.login_user(
        db, UserLogin(username="login-user-1", password="s3cret-password")
    )
    assert result.token_type == "bearer"
    payload = jwt.decode(
        result.access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    assert "sub" in payload


async def test_login_user_wrong_password_raises_401(db):
    await service.register_user(
        db,
        UserCreate(
            username="login-user-2",
            email="login-user-2@example.com",
            password="s3cret-password",
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.login_user(db, UserLogin(username="login-user-2", password="wrong-password"))
    assert exc_info.value.status_code == 401


async def test_login_user_unknown_username_raises_401(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.login_user(
            db, UserLogin(username="nobody-logs-in-like-this", password="whatever")
        )
    assert exc_info.value.status_code == 401


# ── get_user_profile / update_current_user ─────────────────────────────────────


async def test_get_user_profile_found(db):
    await service.register_user(
        db,
        UserCreate(
            username="profile-user-1",
            email="profile-user-1@example.com",
            password="s3cret-password",
        ),
    )
    profile = await service.get_user_profile(db, "profile-user-1")
    assert profile.username == "profile-user-1"
    assert not hasattr(profile, "email")


async def test_get_user_profile_not_found(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.get_user_profile(db, "nobody-has-this-profile")
    assert exc_info.value.status_code == 404


async def test_update_current_user(db):
    from backlogg.users.repository import get_user_by_username

    await service.register_user(
        db,
        UserCreate(
            username="update-user-1",
            email="update-user-1@example.com",
            password="s3cret-password",
        ),
    )
    user = await get_user_by_username(db, "update-user-1")

    result = await service.update_current_user(
        db, user, UserUpdate(display_name="Updated Name", bio="Updated bio")
    )
    assert result.display_name == "Updated Name"
    assert result.bio == "Updated bio"
