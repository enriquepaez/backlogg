from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.core.rate_limit import client_ip
from backlogg.search.schemas import SearchParams, SearchResponse
from backlogg.search.service import SearchService

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search the catalog",
    description=(
        "Cross-type search. `q` is optional (min_length=1 when present, 422 if empty); "
        "also supports `date_from`/`date_to`/`rating_external_min`/`rating_external_max` "
        "range filters (inclusive), independently optional and combinable with `q`. "
        "Rate-limited external fallback fires only on zero local hits AND when `q` is "
        "present — external APIs are never queried by date/rating filters alone."
    ),
)
async def search_catalog(
    request: Request,
    params: Annotated[SearchParams, Query()],
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Search across all catalog types using full-text search plus optional filters.

    - q: search query (optional; min_length=1 when present, returns 422 if empty)
    - type: optional content type filter (movie, series, book, game)
    - page: 1-based page number (>=1)
    - limit: results per page (1–100)
    - date_from / date_to: inclusive range on release_date
    - rating_external_min / rating_external_max: inclusive range on rating_external

    The external fallback (fired only when there are no local results AND `q`
    is present) is rate limited per client IP; exceeding it returns 429 with a
    ``Retry-After`` header.
    """
    svc = SearchService(db)
    results, total = await svc.search(
        q=params.q,
        item_type=params.type,
        page=params.page,
        limit=params.limit,
        client_ip=client_ip(request),
        date_from=params.date_from,
        date_to=params.date_to,
        rating_external_min=params.rating_external_min,
        rating_external_max=params.rating_external_max,
    )
    return SearchResponse(results=results, total=total, page=params.page, limit=params.limit)
