"""Tests for backlogg/users/service.py — password hashing and account logic.

Runs against the real test DB. The only external dependency, the S3-compatible
avatar storage (``service._r2``), is mocked in the avatar upload/delete tests
below — never hit a real bucket.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

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


# ── upload_avatar / delete_avatar (feature 51) ──────────────────────────────


def _make_upload_file(
    content: bytes, content_type: str, filename: str = "avatar.png"
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _configure_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://avatars.example.com")


async def _make_avatar_test_user(db, username: str):
    from backlogg.users.repository import get_user_by_username

    await service.register_user(
        db,
        UserCreate(
            username=username,
            email=f"{username}@example.com",
            password="s3cret-password",
        ),
    )
    return await get_user_by_username(db, username)


async def test_upload_avatar_invalid_content_type_raises_422(db, monkeypatch):
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-bad-type")
    file = _make_upload_file(b"not-an-image", "text/plain")

    with patch.object(service._r2, "upload", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_avatar(db, user, file)

    assert exc_info.value.status_code == 422
    mock_upload.assert_not_called()


async def test_upload_avatar_too_large_raises_413(db, monkeypatch):
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-too-big")
    oversized = b"x" * (service._MAX_AVATAR_SIZE_BYTES + 1)
    file = _make_upload_file(oversized, "image/png")

    with patch.object(service._r2, "upload", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_avatar(db, user, file)

    assert exc_info.value.status_code == 413
    mock_upload.assert_not_called()


async def test_upload_avatar_missing_credentials_raises_503(db, monkeypatch):
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    user = await _make_avatar_test_user(db, "avatar-user-no-creds")
    file = _make_upload_file(b"fake-png-bytes", "image/png")

    with patch.object(service._r2, "upload", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_avatar(db, user, file)

    assert exc_info.value.status_code == 503
    assert "test-account" not in str(exc_info.value.detail)
    mock_upload.assert_not_called()


async def test_upload_avatar_endpoint_override_without_account_id_is_configured(db, monkeypatch):
    """R2_ENDPOINT_URL (MinIO/Supabase) makes R2_ACCOUNT_ID unnecessary."""
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "minioadmin")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "minioadmin123")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "avatars")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "http://localhost:9000/avatars")
    user = await _make_avatar_test_user(db, "avatar-user-minio")
    file = _make_upload_file(b"fake-png-bytes", "image/png")
    fake_url = "http://localhost:9000/avatars/avatars/1/fake-uuid.png"

    with patch.object(
        service._r2, "upload", new_callable=AsyncMock, return_value=fake_url
    ) as mock_upload:
        result = await service.upload_avatar(db, user, file)

    assert result.avatar_url == fake_url
    mock_upload.assert_called_once()


async def test_upload_avatar_no_endpoint_and_no_account_id_raises_503(db, monkeypatch):
    """Neither R2_ENDPOINT_URL nor R2_ACCOUNT_ID set -> still unconfigured."""
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://avatars.example.com")
    user = await _make_avatar_test_user(db, "avatar-user-no-endpoint-no-account")
    file = _make_upload_file(b"fake-png-bytes", "image/png")

    with patch.object(service._r2, "upload", new_callable=AsyncMock) as mock_upload:
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_avatar(db, user, file)

    assert exc_info.value.status_code == 503
    mock_upload.assert_not_called()


async def test_upload_avatar_success_updates_avatar_url(db, monkeypatch):
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-success")
    file = _make_upload_file(b"fake-png-bytes", "image/png")
    fake_url = "https://avatars.example.com/avatars/1/fake-uuid.png"

    with patch.object(
        service._r2, "upload", new_callable=AsyncMock, return_value=fake_url
    ) as mock_upload:
        result = await service.upload_avatar(db, user, file)

    assert result.avatar_url == fake_url
    mock_upload.assert_called_once()
    call_kwargs = mock_upload.call_args.kwargs
    assert call_kwargs["key"].startswith(f"avatars/{user.id}/")
    assert call_kwargs["key"].endswith(".png")
    assert call_kwargs["content_type"] == "image/png"

    from backlogg.users.repository import get_user_by_username

    persisted = await get_user_by_username(db, "avatar-user-success")
    assert persisted.avatar_url == fake_url


async def test_upload_avatar_overwrites_previous_avatar_url(db, monkeypatch):
    """Uploading a file overwrites any avatar_url set via PATCH /v1/users/me."""
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-overwrite")
    await service.update_current_user(
        db, user, UserUpdate(avatar_url="https://external.example.com/old.png")
    )
    file = _make_upload_file(b"fake-png-bytes", "image/webp")
    fake_url = "https://avatars.example.com/avatars/1/new.webp"

    with patch.object(service._r2, "upload", new_callable=AsyncMock, return_value=fake_url):
        result = await service.upload_avatar(db, user, file)

    assert result.avatar_url == fake_url


async def test_delete_avatar_deletes_r2_object_and_clears_avatar_url(db, monkeypatch):
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-delete")
    key = f"avatars/{user.id}/existing.png"
    await service.update_current_user(
        db, user, UserUpdate(avatar_url=f"https://avatars.example.com/{key}")
    )

    with patch.object(service._r2, "delete", new_callable=AsyncMock) as mock_delete:
        await service.delete_avatar(db, user)

    mock_delete.assert_called_once_with(key=key)

    from backlogg.users.repository import get_user_by_username

    persisted = await get_user_by_username(db, "avatar-user-delete")
    assert persisted.avatar_url is None


async def test_delete_avatar_already_null_is_idempotent(db, monkeypatch):
    _configure_r2(monkeypatch)
    user = await _make_avatar_test_user(db, "avatar-user-delete-noop")
    assert user.avatar_url is None

    with patch.object(service._r2, "delete", new_callable=AsyncMock) as mock_delete:
        await service.delete_avatar(db, user)

    mock_delete.assert_not_called()
