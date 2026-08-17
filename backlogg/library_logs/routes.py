from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.library_logs import service
from backlogg.library_logs.schemas import UserLogListOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

# DELETE /log/{id} — deleting a log entry is not scoped to a content type, so
# it lives under its own prefix rather than one of the four content routers
# (same precedent as backlogg.ratings.routes.ratings_router's /{id}/like).
log_router = APIRouter(prefix="/log", tags=["library_logs"])

# GET /users/{username}/log — public, cross-type. Registered under the same
# "/users" prefix as backlogg.users.routes.users_router; the extra "/log"
# path segment means the two routers never collide.
user_log_router = APIRouter(prefix="/users", tags=["library_logs"])


@log_router.delete(
    "/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete own log entry",
    description="Remove the caller's own log entry. 404 if missing or owned by another user. Auth.",
)
async def delete_log(
    log_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_log_entry(db, log_id=log_id, user=current_user)


@user_log_router.get(
    "/{username}/log",
    response_model=UserLogListOut,
    summary="Get a user's log history",
    description="Public, paginated, cross-type log history for a user, newest logged_on first.",
)
async def get_user_log(
    username: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_log(db, username=username, page=page, limit=limit)
