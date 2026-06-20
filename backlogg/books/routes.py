from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import service
from backlogg.books.schemas import BookListOut, BookOut, BookSortEnum
from backlogg.core.database import get_db

router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=BookListOut)
async def list_books(
    genre: str | None = Query(default=None, description="Filter by genre slug"),
    sort: BookSortEnum = Query(default=BookSortEnum.rating_desc, description="Sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_books(db, genre=genre, sort=sort, page=page, limit=limit)


@router.get("/{slug}", response_model=BookOut)
async def get_book(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_book(db, slug)
