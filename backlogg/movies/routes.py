from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.movies import service
from backlogg.movies.schemas import MovieListOut, MovieOut, MovieSortEnum, SimilarMoviesOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

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


@router.get("/{slug}/similar", response_model=SimilarMoviesOut)
async def get_similar_movies(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_similar_movies(db, slug)


@router.get("/{slug}/ratings", response_model=RatingListOut)
async def list_movie_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db, item_type="MOVIE", slug=slug, page=page, limit=limit
    )


@router.put("/{slug}/rating", response_model=RatingOut)
async def rate_movie(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="MOVIE", slug=slug, payload=payload, user=current_user
    )


@router.delete("/{slug}/rating", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="MOVIE", slug=slug, user=current_user)


@router.get("/{slug}", response_model=MovieOut)
async def get_movie(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_movie(db, slug)
