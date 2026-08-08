from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.genres import service
from backlogg.genres.schemas import GenreListOut, ItemTypeEnum

router = APIRouter(prefix="/genres", tags=["genres"])


@router.get(
    "",
    response_model=GenreListOut,
    summary="List genres",
    description="Genres with live item counts; optional content-type filter (all types if unset).",
)
async def list_genres(
    type: ItemTypeEnum | None = Query(
        default=None,
        description="Filter by item type: movie, series, book, game",
    ),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_genres(db, item_type=type)
