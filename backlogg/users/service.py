from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.config import settings
from backlogg.follows import repository as follows_repo
from backlogg.library import repository as library_repo
from backlogg.library.schemas import LibraryCounts
from backlogg.users import repository as repo
from backlogg.users.auth import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from backlogg.users.models import User
from backlogg.users.schemas import (
    LogoutRequest,
    RefreshRequest,
    TokenPairOut,
    UserCreate,
    UserLogin,
    UserMeOut,
    UserOut,
    UserUpdate,
)

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2. Never log or persist the plaintext."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored argon2 hash."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def register_user(db: AsyncSession, payload: UserCreate) -> UserMeOut:
    """Create a new user account. Raises 409 if username/email is already taken."""
    if await repo.get_user_by_username(db, payload.username) is not None:
        raise HTTPException(status_code=409, detail="Username already taken")
    if await repo.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await repo.create_user(
        db,
        {
            "username": payload.username,
            "email": payload.email,
            "password_hash": hash_password(payload.password),
            "display_name": payload.display_name,
        },
    )
    await db.commit()
    return UserMeOut.model_validate(user)


async def _issue_refresh_token(db: AsyncSession, user_id: int) -> str:
    """Generate an opaque refresh token, persist only its hash, return the plaintext.

    The plaintext is returned to the caller for the HTTP response only; it is
    never persisted or logged.
    """
    plaintext = generate_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_EXPIRE_DAYS)
    await repo.create_refresh_token(db, user_id, hash_refresh_token(plaintext), expires_at)
    return plaintext


async def login_user(db: AsyncSession, payload: UserLogin) -> TokenPairOut:
    """Validate credentials and issue an access + refresh token pair.

    Raises 401 on any credential mismatch.
    """
    user = await repo.get_user_by_username(db, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(user.id)
    refresh_token = await _issue_refresh_token(db, user.id)
    await db.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)


async def refresh_tokens(db: AsyncSession, payload: RefreshRequest) -> TokenPairOut:
    """Rotate a refresh token: validate, revoke the used one, issue a new pair.

    Raises 401 if the token is unknown, expired, or already revoked. Presenting
    an already-revoked token is treated as reuse: as a defense, every still-active
    refresh token for that user is revoked.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await repo.get_refresh_token_by_hash(db, token_hash)
    now = datetime.now(UTC)

    if stored is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.revoked_at is not None:
        # Reuse detected: revoke the whole active set for this user.
        await repo.revoke_all_active_for_user(db, stored.user_id, now)
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.expires_at <= now:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Rotate: revoke the presented token and issue a fresh pair.
    await repo.revoke_refresh_token(db, stored, now)
    access_token = create_access_token(stored.user_id)
    refresh_token = await _issue_refresh_token(db, stored.user_id)
    await db.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)


async def logout_user(db: AsyncSession, user: User, payload: LogoutRequest) -> None:
    """Revoke the presented refresh token. Idempotent — revoking twice is a no-op.

    Only revokes a token that belongs to the authenticated user; unknown or
    foreign tokens are silently ignored so logout never leaks token existence.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await repo.get_refresh_token_by_hash(db, token_hash)
    if stored is not None and stored.user_id == user.id:
        await repo.revoke_refresh_token(db, stored, datetime.now(UTC))
    await db.commit()


def get_current_user_profile(user: User) -> UserMeOut:
    """Convert the authenticated User (loaded by the auth dependency) to UserMeOut."""
    return UserMeOut.model_validate(user)


async def get_user_profile(db: AsyncSession, username: str) -> UserOut:
    """Return the public profile for a username, or raise HTTP 404.

    Includes follower_count/following_count from the follows domain.
    """
    user = await repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    follower_count = await follows_repo.count_followers(db, user.id)
    following_count = await follows_repo.count_following(db, user.id)
    library_counts = await library_repo.count_by_status(db, user.id)
    return UserOut(
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        follower_count=follower_count,
        following_count=following_count,
        library_counts=LibraryCounts(**library_counts),
    )


async def update_current_user(db: AsyncSession, user: User, payload: UserUpdate) -> UserMeOut:
    """Update the authenticated user's display_name/bio/avatar_url."""
    data = payload.model_dump(exclude_unset=True)
    updated = await repo.update_user(db, user, data)
    await db.commit()
    return UserMeOut.model_validate(updated)
