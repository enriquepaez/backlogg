from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.series import service
from backlogg.series.schemas import SeriesOut

router = APIRouter(prefix="/series", tags=["series"])


@router.get("/{slug}", response_model=SeriesOut)
async def get_series(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_series(db, slug)
