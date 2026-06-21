from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.trending import service
from backlogg.trending.schemas import ItemTypeEnum, PeriodEnum, TrendingOut

router = APIRouter(prefix="/trending", tags=["trending"])


@router.get("", response_model=TrendingOut)
async def get_trending(
    type: ItemTypeEnum | None = None,
    period: PeriodEnum = PeriodEnum.week,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_trending(db, item_type=type, period=period)
