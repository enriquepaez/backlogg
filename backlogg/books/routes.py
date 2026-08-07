from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import service
from backlogg.books.schemas import BookListOut, BookOut, BookSortEnum
from backlogg.core.database import get_db
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

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


@router.get("/{slug}/ratings", response_model=RatingListOut)
async def list_book_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db, item_type="BOOK", slug=slug, page=page, limit=limit
    )


@router.put("/{slug}/rating", response_model=RatingOut)
async def rate_book(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="BOOK", slug=slug, payload=payload, user=current_user
    )


@router.delete("/{slug}/rating", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="BOOK", slug=slug, user=current_user)


@router.get("/{slug}", response_model=BookOut)
async def get_book(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_book(db, slug)
