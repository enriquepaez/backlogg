from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.follows import service
from backlogg.follows.schemas import FollowListOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

# Registered under the same "/users" prefix as backlogg.users.routes; the extra
# "/follow", "/followers", "/following" path segments mean the routers never
# collide with GET /users/{username}.
follows_router = APIRouter(prefix="/users", tags=["follows"])


@follows_router.post("/{username}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.follow_user(db, username=username, user=current_user)


@follows_router.delete("/{username}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_user(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.unfollow_user(db, username=username, user=current_user)


@follows_router.get("/{username}/followers", response_model=FollowListOut)
async def list_followers(
    username: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_followers(db, username=username, page=page, limit=limit)


@follows_router.get("/{username}/following", response_model=FollowListOut)
async def list_following(
    username: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_following(db, username=username, page=page, limit=limit)
