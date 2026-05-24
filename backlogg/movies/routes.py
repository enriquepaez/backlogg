from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.movies import service
from backlogg.movies.schemas import MovieOut

router = APIRouter(prefix="/movies", tags=["movies"])


@router.get("/{slug}", response_model=MovieOut)
async def get_movie(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_movie(db, slug)
