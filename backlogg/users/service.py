from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.users import repository as repo
from backlogg.users.auth import create_access_token
from backlogg.users.models import User
from backlogg.users.schemas import (
    TokenOut,
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


async def login_user(db: AsyncSession, payload: UserLogin) -> TokenOut:
    """Validate credentials and issue a JWT. Raises 401 on any mismatch."""
    user = await repo.get_user_by_username(db, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user.id)
    return TokenOut(access_token=token)


def get_current_user_profile(user: User) -> UserMeOut:
    """Convert the authenticated User (loaded by the auth dependency) to UserMeOut."""
    return UserMeOut.model_validate(user)


async def get_user_profile(db: AsyncSession, username: str) -> UserOut:
    """Return the public profile for a username, or raise HTTP 404."""
    user = await repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut.model_validate(user)


async def update_current_user(db: AsyncSession, user: User, payload: UserUpdate) -> UserMeOut:
    """Update the authenticated user's display_name/bio/avatar_url."""
    data = payload.model_dump(exclude_unset=True)
    updated = await repo.update_user(db, user, data)
    await db.commit()
    return UserMeOut.model_validate(updated)
