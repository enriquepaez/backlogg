from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.library import service
from backlogg.library.schemas import LibraryListOut, LibraryStatus, LibraryTypeFilter

# GET /users/{username}/library — public, cross-type. Registered under the same
# "/users" prefix as backlogg.users.routes.users_router; the extra "/library"
# path segment means the two routers never collide.
user_library_router = APIRouter(prefix="/users", tags=["library"])


@user_library_router.get("/{username}/library", response_model=LibraryListOut)
async def get_user_library(
    username: str,
    status: LibraryStatus | None = Query(default=None, description="Filter by backlog status"),
    type: LibraryTypeFilter | None = Query(default=None, description="Filter by content type"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_library(
        db, username=username, status=status, type_filter=type, page=page, limit=limit
    )
