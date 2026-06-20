from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.series import service
from backlogg.series.schemas import SeriesListOut, SeriesOut, SeriesSortEnum

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


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_series(db, slug)
