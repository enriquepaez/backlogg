from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.users.models import AccountToken, RefreshToken, User


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: dict) -> User:
    user = User(**data)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user: User, data: dict) -> User:
    for key, value in data.items():
        setattr(user, key, value)
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    """Delete a user row and flush.

    Every table referencing ``users.id`` (ratings, review_likes, follows,
    library_entries, user_lists, notifications, refresh_tokens, account_tokens)
    declares ``ON DELETE CASCADE``, so the flush removes all associated rows at
    the DB level in the same transaction. The flush is what makes the cascade
    visible to a subsequent aggregate recompute in the same session.
    """
    await db.delete(user)
    await db.flush()


# ── Refresh tokens ────────────────────────────────────────────────────────────


async def create_refresh_token(
    db: AsyncSession, user_id: int, token_hash: str, expires_at: datetime
) -> RefreshToken:
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token


async def get_refresh_token_by_hash(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def revoke_refresh_token(db: AsyncSession, token: RefreshToken, now: datetime) -> None:
    """Mark a single refresh token as revoked. Idempotent — no-op if already revoked."""
    if token.revoked_at is None:
        token.revoked_at = now
        await db.flush()


async def revoke_all_active_for_user(db: AsyncSession, user_id: int, now: datetime) -> None:
    """Revoke every still-active refresh token for a user (reuse defense)."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()


# ── Account recovery tokens (email verify / password reset) ─────────────────────


async def create_account_token(
    db: AsyncSession,
    user_id: int,
    token_hash: str,
    purpose: str,
    expires_at: datetime,
) -> AccountToken:
    token = AccountToken(
        user_id=user_id,
        token_hash=token_hash,
        purpose=purpose,
        expires_at=expires_at,
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token


async def get_account_token_by_hash(db: AsyncSession, token_hash: str) -> AccountToken | None:
    result = await db.execute(select(AccountToken).where(AccountToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def consume_account_token(db: AsyncSession, token: AccountToken, now: datetime) -> None:
    """Stamp ``consumed_at`` so the token can never be used again."""
    token.consumed_at = now
    await db.flush()


async def set_email_verified(db: AsyncSession, user_id: int) -> None:
    await db.execute(update(User).where(User.id == user_id).values(email_verified=True))
    await db.flush()


async def set_password_hash(db: AsyncSession, user_id: int, password_hash: str) -> None:
    await db.execute(update(User).where(User.id == user_id).values(password_hash=password_hash))
    await db.flush()
