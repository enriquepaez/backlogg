"""User authentication: JWT issuance and the get_current_user dependency.

Tokens are signed with settings.JWT_SECRET_KEY using settings.JWT_ALGORITHM
and expire after settings.JWT_EXPIRE_MINUTES minutes. The subject claim
("sub") holds the user's id.

Rules:
- Authorization header missing → 401
- Token malformed/invalid signature → 401
- Token expired → 401
- Token valid but the user no longer exists → 401
"""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.config import settings
from backlogg.core.database import get_db
from backlogg.users import repository as repo
from backlogg.users.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    """Issue a signed JWT for the given user id."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that resolves the authenticated User from a Bearer token.

    Raises:
        HTTPException 401: Authorization header is missing, the token is
            invalid/expired, or it no longer maps to an existing user.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        user = await repo.get_user_by_id(db, int(user_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """FastAPI dependency for endpoints where authentication is optional.

    Returns the authenticated ``User`` when a valid Bearer token is present,
    or ``None`` when the Authorization header is missing, the token is
    invalid/expired, or it no longer maps to an existing user. Never raises
    401 — public endpoints stay reachable while still recognising the caller
    when possible (e.g. to attach ``viewer_status``).
    """
    if credentials is None:
        return None

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    try:
        user = await repo.get_user_by_id(db, int(user_id))
    except (TypeError, ValueError):
        return None

    return user
