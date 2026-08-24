from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryEntryIn, LibraryStatusOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.series import service
from backlogg.series.schemas import SeriesListOut, SeriesListParams, SeriesOut, SimilarSeriesListOut
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

router = APIRouter(prefix="/series", tags=["series"])


@router.get(
    "",
    response_model=SeriesListOut,
    summary="List series",
    description=(
        "Paginated list of catalogued series (no external fallback); genre filter + sort, "
        "plus search/date-range/rating-range filters (feature 50)."
    ),
)
async def list_series(
    params: Annotated[SeriesListParams, Query()],
    db: AsyncSession = Depends(get_db),
):
    return await service.list_series(
        db,
        genre=params.genre,
        sort=params.sort,
        page=params.page,
        limit=params.limit,
        filters=params,
    )


@router.get(
    "/{slug}/similar",
    response_model=SimilarSeriesListOut,
    summary="Similar series",
    description="Up to 10 similar series (TMDB). New items are persisted locally.",
)
async def get_similar_series(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_similar_series(db, slug)


@router.get(
    "/{slug}/ratings",
    response_model=RatingListOut,
    summary="List series ratings",
    description="Public, paginated ratings & reviews for a series, newest first.",
)
async def list_series_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db,
        item_type="SERIES",
        slug=slug,
        page=page,
        limit=limit,
        caller_id=current_user.id if current_user else None,
    )


@router.put(
    "/{slug}/rating",
    response_model=RatingOut,
    summary="Rate a series",
    description="Upsert the caller's score/review (full replace); recomputes aggregates. Auth.",
)
async def rate_series(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="SERIES", slug=slug, payload=payload, user=current_user
    )


@router.delete(
    "/{slug}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete own series rating",
    description="Remove the caller's rating and recompute aggregates. Requires auth.",
)
async def delete_series_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="SERIES", slug=slug, user=current_user)


@router.put(
    "/{slug}/library",
    response_model=LibraryStatusOut,
    summary="Set series library status",
    description="Upsert the caller's backlog status for this series. Requires auth.",
)
async def set_series_library(
    slug: str,
    payload: LibraryEntryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_service.set_library_status(
        db, item_type="SERIES", slug=slug, status=payload.status, user=current_user
    )


@router.delete(
    "/{slug}/library",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove series from library",
    description="Delete the caller's library entry for this series. Requires auth.",
)
async def delete_series_library(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await library_service.remove_library_entry(db, item_type="SERIES", slug=slug, user=current_user)


@router.get(
    "/{slug}",
    response_model=SeriesOut,
    summary="Get series detail",
    description="Full series detail; on-demand fallback. Auth optional (adds viewer_status).",
)
async def get_series(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    viewer_id = current_user.id if current_user else None
    return await service.get_series(db, slug, viewer_id=viewer_id)
