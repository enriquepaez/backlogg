from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryEntryIn, LibraryStatusOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.series import service
from backlogg.series.schemas import SeriesListOut, SeriesOut, SeriesSortEnum, SimilarSeriesListOut
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

router = APIRouter(prefix="/series", tags=["series"])


@router.get("", response_model=SeriesListOut)
async def list_series(
    genre: str | None = Query(default=None, description="Filter by genre slug"),
    sort: SeriesSortEnum = Query(default=SeriesSortEnum.rating_desc, description="Sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_series(db, genre=genre, sort=sort, page=page, limit=limit)


@router.get("/{slug}/similar", response_model=SimilarSeriesListOut)
async def get_similar_series(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_similar_series(db, slug)


@router.get("/{slug}/ratings", response_model=RatingListOut)
async def list_series_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db, item_type="SERIES", slug=slug, page=page, limit=limit
    )


@router.put("/{slug}/rating", response_model=RatingOut)
async def rate_series(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="SERIES", slug=slug, payload=payload, user=current_user
    )


@router.delete("/{slug}/rating", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="SERIES", slug=slug, user=current_user)


@router.put("/{slug}/library", response_model=LibraryStatusOut)
async def set_series_library(
    slug: str,
    payload: LibraryEntryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_service.set_library_status(
        db, item_type="SERIES", slug=slug, status=payload.status, user=current_user
    )


@router.delete("/{slug}/library", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series_library(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await library_service.remove_library_entry(db, item_type="SERIES", slug=slug, user=current_user)


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    viewer_id = current_user.id if current_user else None
    return await service.get_series(db, slug, viewer_id=viewer_id)
