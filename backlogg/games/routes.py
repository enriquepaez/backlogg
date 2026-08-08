from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.games import service
from backlogg.games.schemas import GameListOut, GameOut, GameSortEnum
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryEntryIn, LibraryStatusOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

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


@router.get("/{slug}/ratings", response_model=RatingListOut)
async def list_game_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db, item_type="GAME", slug=slug, page=page, limit=limit
    )


@router.put("/{slug}/rating", response_model=RatingOut)
async def rate_game(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="GAME", slug=slug, payload=payload, user=current_user
    )


@router.delete("/{slug}/rating", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="GAME", slug=slug, user=current_user)


@router.put("/{slug}/library", response_model=LibraryStatusOut)
async def set_game_library(
    slug: str,
    payload: LibraryEntryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_service.set_library_status(
        db, item_type="GAME", slug=slug, status=payload.status, user=current_user
    )


@router.delete("/{slug}/library", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game_library(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await library_service.remove_library_entry(db, item_type="GAME", slug=slug, user=current_user)


@router.get("/{slug}", response_model=GameOut)
async def get_game(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    viewer_id = current_user.id if current_user else None
    return await service.get_game(db, slug, viewer_id=viewer_id)
