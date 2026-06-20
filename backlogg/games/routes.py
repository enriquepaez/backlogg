from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.games import service
from backlogg.games.schemas import GameListOut, GameOut, GameSortEnum

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=GameListOut)
async def list_games(
    genre: str | None = Query(default=None, description="Filter by genre slug"),
    sort: GameSortEnum = Query(default=GameSortEnum.rating_desc, description="Sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_games(db, genre=genre, sort=sort, page=page, limit=limit)


@router.get("/{slug}", response_model=GameOut)
async def get_game(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_game(db, slug)
