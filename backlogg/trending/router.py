from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.trending import service
from backlogg.trending.schemas import ItemTypeEnum, PeriodEnum, TrendingOut

router = APIRouter(prefix="/trending", tags=["trending"])


@router.get(
    "",
    response_model=TrendingOut,
    summary="Get trending items",
    description=(
        "Up to 20 trending items. Movies/series come from TMDB's Trending API "
        "(new items are persisted locally). Books/games have no external "
        "trending endpoint, so they use a local popularity heuristic "
        "(rating_internal DESC NULLS LAST, rating_external DESC NULLS LAST as "
        "tie-break) — period is accepted but has no effect for those two types."
    ),
)
async def get_trending(
    type: ItemTypeEnum | None = None,
    period: PeriodEnum = PeriodEnum.week,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_trending(db, item_type=type, period=period)
