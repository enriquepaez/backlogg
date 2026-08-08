from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin.auth import verify_api_key
from backlogg.core.database import get_db
from backlogg.moderation import service
from backlogg.moderation.schemas import ReviewModerationOut, UserModerationOut

# Admin moderation actions. Same X-API-Key gate and "/admin" prefix as
# backlogg.admin.router / backlogg.reports.admin_reports_router, applied at the
# router level so every action requires the header.
admin_moderation_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(verify_api_key)]
)


@admin_moderation_router.post(
    "/reviews/{rating_id}/hide",
    response_model=ReviewModerationOut,
    summary="Hide a review",
    description=(
        "Hide a review (a `user_ratings` row) from public listings, the feed and "
        "the rating aggregates. Idempotent. 404 if the review does not exist. "
        "Requires `X-API-Key`."
    ),
)
async def hide_review(
    rating_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReviewModerationOut:
    return await service.set_review_hidden(db, rating_id=rating_id, hidden=True)


@admin_moderation_router.post(
    "/reviews/{rating_id}/unhide",
    response_model=ReviewModerationOut,
    summary="Unhide a review",
    description=(
        "Restore a previously hidden review. Idempotent. 404 if the review does "
        "not exist. Requires `X-API-Key`."
    ),
)
async def unhide_review(
    rating_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReviewModerationOut:
    return await service.set_review_hidden(db, rating_id=rating_id, hidden=False)


@admin_moderation_router.post(
    "/users/{username}/ban",
    response_model=UserModerationOut,
    summary="Ban a user",
    description=(
        "Ban a user: they can no longer log in or refresh, and all of their "
        "reviews become invisible (excluded from listings, feed and aggregates). "
        "Idempotent. 404 if the user does not exist. Requires `X-API-Key`."
    ),
)
async def ban_user(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserModerationOut:
    return await service.set_user_banned(db, username=username, banned=True)


@admin_moderation_router.post(
    "/users/{username}/unban",
    response_model=UserModerationOut,
    summary="Unban a user",
    description=(
        "Lift a ban: the user can log in again and their reviews become visible "
        "once more. Idempotent. 404 if the user does not exist. Requires `X-API-Key`."
    ),
)
async def unban_user(
    username: str,
    db: AsyncSession = Depends(get_db),
) -> UserModerationOut:
    return await service.set_user_banned(db, username=username, banned=False)
