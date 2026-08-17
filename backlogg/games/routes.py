from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.games import service
from backlogg.games.schemas import GameListOut, GameListParams, GameOut, SimilarGameListOut
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryEntryIn, LibraryStatusOut
from backlogg.library_logs import service as library_logs_service
from backlogg.library_logs.schemas import LogIn, LogListOut, LogOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

router = APIRouter(prefix="/games", tags=["games"])


@router.get(
    "",
    response_model=GameListOut,
    summary="List games",
    description=(
        "Paginated list of catalogued games (no external fallback); genre filter + sort, "
        "plus search/date-range/rating-range filters (feature 50)."
    ),
)
async def list_games(
    params: Annotated[GameListParams, Query()],
    db: AsyncSession = Depends(get_db),
):
    return await service.list_games(
        db,
        genre=params.genre,
        sort=params.sort,
        page=params.page,
        limit=params.limit,
        filters=params,
    )


@router.get(
    "/{slug}/similar",
    response_model=SimilarGameListOut,
    summary="Similar games",
    description="Up to 10 similar games (IGDB similar_games). New items are persisted locally.",
)
async def get_similar_games(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_similar_games(db, slug)


@router.get(
    "/{slug}/ratings",
    response_model=RatingListOut,
    summary="List game ratings",
    description="Public, paginated ratings & reviews for a game, newest first.",
)
async def list_game_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db,
        item_type="GAME",
        slug=slug,
        page=page,
        limit=limit,
        caller_id=current_user.id if current_user else None,
    )


@router.put(
    "/{slug}/rating",
    response_model=RatingOut,
    summary="Rate a game",
    description="Upsert the caller's score/review (full replace); recomputes aggregates. Auth.",
)
async def rate_game(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="GAME", slug=slug, payload=payload, user=current_user
    )


@router.delete(
    "/{slug}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete own game rating",
    description="Remove the caller's rating and recompute aggregates. Requires auth.",
)
async def delete_game_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="GAME", slug=slug, user=current_user)


@router.put(
    "/{slug}/library",
    response_model=LibraryStatusOut,
    summary="Set game library status",
    description="Upsert the caller's backlog status for this game. Requires auth.",
)
async def set_game_library(
    slug: str,
    payload: LibraryEntryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_service.set_library_status(
        db, item_type="GAME", slug=slug, status=payload.status, user=current_user
    )


@router.delete(
    "/{slug}/library",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove game from library",
    description="Delete the caller's library entry for this game. Requires auth.",
)
async def delete_game_library(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await library_service.remove_library_entry(db, item_type="GAME", slug=slug, user=current_user)


@router.post(
    "/{slug}/log",
    response_model=LogOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a game session",
    description="Create a dated log entry (replay/session) for this game; never upserts. Auth.",
)
async def log_game(
    slug: str,
    payload: LogIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_logs_service.create_log_entry(
        db, item_type="GAME", slug=slug, payload=payload, user=current_user
    )


@router.get(
    "/{slug}/log",
    response_model=LogListOut,
    summary="List game log entries",
    description="Public, paginated log entries for a game, newest logged_on first.",
)
async def list_game_log(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await library_logs_service.list_item_log(
        db, item_type="GAME", slug=slug, page=page, limit=limit
    )


@router.get(
    "/{slug}",
    response_model=GameOut,
    summary="Get game detail",
    description="Full game detail; on-demand IGDB fallback. Auth optional (adds viewer_status).",
)
async def get_game(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    viewer_id = current_user.id if current_user else None
    return await service.get_game(db, slug, viewer_id=viewer_id)
