from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.ratings import service
from backlogg.ratings.schemas import UserReviewListOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

# POST/DELETE /ratings/{rating_id}/like — liking a review is not scoped to a
# content type, so it lives under its own prefix rather than one of the four
# content routers.
ratings_router = APIRouter(prefix="/ratings", tags=["ratings"])

# GET /users/{username}/reviews — public, cross-type. Registered under the
# same "/users" prefix as backlogg.users.routes.users_router; the extra
# "/reviews" path segment means the two routers never collide.
user_reviews_router = APIRouter(prefix="/users", tags=["ratings"])


@ratings_router.post("/{rating_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_review(
    rating_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.like_review(db, rating_id=rating_id, user=current_user)


@ratings_router.delete("/{rating_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_review(
    rating_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.unlike_review(db, rating_id=rating_id, user=current_user)


@user_reviews_router.get("/{username}/reviews", response_model=UserReviewListOut)
async def get_user_reviews(
    username: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_reviews(db, username=username, page=page, limit=limit)
