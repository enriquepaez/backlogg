from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.feed import service
from backlogg.feed.schemas import FeedListOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

feed_router = APIRouter(prefix="/feed", tags=["feed"])


@feed_router.get("", response_model=FeedListOut)
async def get_feed(
    tab: Literal["following", "popular"] = Query(
        default="following", description="Feed tab: following or popular"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_feed(db, caller=current_user, tab=tab, page=page, limit=limit)
