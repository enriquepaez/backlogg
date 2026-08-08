from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.core.rate_limit import client_ip
from backlogg.search.schemas import SearchResponse
from backlogg.search.service import SearchService

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search the catalog",
    description="Cross-type full-text search; rate-limited external fallback on zero local hits.",
)
async def search_catalog(
    request: Request,
    q: str = Query(min_length=1),
    type: Literal["movie", "series", "book", "game"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Search across all catalog types using full-text search.

    - q: search query (required, min_length=1; returns 422 if absent or empty)
    - type: optional content type filter (movie, series, book, game)
    - page: 1-based page number (>=1)
    - limit: results per page (1–100)

    The external fallback (fired only when there are no local results) is rate
    limited per client IP; exceeding it returns 429 with a ``Retry-After`` header.
    """
    svc = SearchService(db)
    results, total = await svc.search(
        q=q, item_type=type, page=page, limit=limit, client_ip=client_ip(request)
    )
    return SearchResponse(results=results, total=total, page=page, limit=limit)
