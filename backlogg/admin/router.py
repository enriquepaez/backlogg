"""Admin router — internal endpoints for manual sync triggering.

No authentication is required in the MVP.  These endpoints are intended
for internal/testing use only.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException

from backlogg.admin.schemas import SyncResponse
from backlogg.scheduler.jobs import sync_books, sync_games, sync_movies, sync_series

router = APIRouter(prefix="/admin", tags=["admin"])

_SYNC_HANDLERS = {
    "movie": sync_movies,
    "series": sync_series,
    "book": sync_books,
    "game": sync_games,
}

SyncType = Literal["movie", "series", "book", "game"]


@router.post("/sync/{type}", status_code=202, response_model=SyncResponse)
async def trigger_sync(type: SyncType) -> SyncResponse:
    """Trigger a manual sync for the given content type.

    ``type`` must be one of: ``movie``, ``series``, ``book``, ``game``.

    The sync runs in the background and returns immediately with 202.
    """
    handler = _SYNC_HANDLERS.get(type)
    if handler is None:
        raise HTTPException(status_code=422, detail=f"Unknown sync type: {type}")

    asyncio.create_task(handler())

    return SyncResponse(status="ok", type=type)
