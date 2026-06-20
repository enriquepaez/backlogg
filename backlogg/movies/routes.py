from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.movies import service
from backlogg.movies.schemas import MovieListOut, MovieOut, MovieSortEnum

router = APIRouter(prefix="/movies", tags=["movies"])


@router.get("", response_model=MovieListOut)
async def list_movies(
    genre: str | None = Query(default=None, description="Filter by genre slug"),
    sort: MovieSortEnum = Query(default=MovieSortEnum.rating_desc, description="Sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_movies(db, genre=genre, sort=sort, page=page, limit=limit)


@router.get("/{slug}", response_model=MovieOut)
async def get_movie(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_movie(db, slug)
