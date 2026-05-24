from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import service
from backlogg.books.schemas import BookOut
from backlogg.core.database import get_db

router = APIRouter(prefix="/books", tags=["books"])


@router.get("/{slug}", response_model=BookOut)
async def get_book(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_book(db, slug)
