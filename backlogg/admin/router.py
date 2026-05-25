"""Admin router — internal endpoints for manual sync triggering.

No authentication is required in the MVP.  These endpoints are intended
for internal/testing use only.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import service as admin_service
from backlogg.admin.schemas import StatsResponse, SyncResponse
from backlogg.core.database import get_db
from backlogg.scheduler.jobs import sync_books, sync_games, sync_movies, sync_series

router = APIRouter(prefix="/admin", tags=["admin"])

_SYNC_HANDLERS = {
    "movie": sync_movies,
    "series": sync_series,
    "book": sync_books,
    "game": sync_games,
}

SyncType = Literal["movie", "series", "book", "game"]


@router.post("/sync/{type}", status_code=200, response_model=SyncResponse)
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


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    """Return item counts and last sync timestamp for each content type.

    ``count`` is a live COUNT(*) from each table.
    ``last_synced_at`` is MAX(last_synced_at); null if the table is empty.
    """
    return await admin_service.get_stats(db)
