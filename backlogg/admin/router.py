"""Admin router — internal endpoints for manual sync triggering.

All endpoints require the X-API-Key header validated by verify_api_key.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import service as admin_service
from backlogg.admin.auth import verify_api_key
from backlogg.admin.schemas import AdminUserListOut, StatsResponse, SyncResponse
from backlogg.core.database import get_db
from backlogg.scheduler.jobs import sync_books, sync_games, sync_movies, sync_series

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_api_key)])

_SYNC_HANDLERS = {
    "movie": sync_movies,
    "series": sync_series,
    "book": sync_books,
    "game": sync_games,
}

SyncType = Literal["movie", "series", "book", "game"]


@router.post(
    "/sync/{type}",
    status_code=200,
    response_model=SyncResponse,
    summary="Trigger content sync",
    description="Run a synchronous sync slice and block until it finishes. Requires `X-API-Key`.",
)
async def trigger_sync(type: SyncType) -> SyncResponse:
    """Trigger a synchronous sync for the given content type.

    ``type`` must be one of: ``movie``, ``series``, ``book``, ``game``.

    The sync runs to completion and returns the result with 200.
    """
    handler = _SYNC_HANDLERS.get(type)
    if handler is None:
        raise HTTPException(status_code=422, detail=f"Unknown sync type: {type}")

    result = await handler()

    return SyncResponse(type=type, **result)


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Catalog stats",
    description="Per-type item counts and last sync timestamp. Requires `X-API-Key`.",
)
async def get_stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    """Return item counts and last sync timestamp for each content type.

    ``count`` is a live COUNT(*) from each table.
    ``last_synced_at`` is MAX(last_synced_at); null if the table is empty.
    """
    return await admin_service.get_stats(db)


@router.get(
    "/users",
    response_model=AdminUserListOut,
    summary="List users",
    description=(
        "Paginated user listing for the admin backoffice, ordered by `username` asc. "
        "Optional `is_banned`/`is_admin` filters, combinable and independent — omitting "
        "both returns every user. Never includes `email` (PII minimization). Requires "
        "`X-API-Key`."
    ),
)
async def list_users(
    is_banned: bool | None = Query(default=None, description="Filter by ban status"),
    is_admin: bool | None = Query(default=None, description="Filter by admin role"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> AdminUserListOut:
    """Return a paginated, filterable listing of users for the admin backoffice."""
    return await admin_service.list_users(
        db, is_banned=is_banned, is_admin=is_admin, page=page, limit=limit
    )
