from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.games import service
from backlogg.games.schemas import GameOut

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/{slug}", response_model=GameOut)
async def get_game(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_game(db, slug)
