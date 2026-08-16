from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books import service
from backlogg.books.schemas import BookListOut, BookOut, BookSortEnum, SimilarBooksOut
from backlogg.core.database import get_db
from backlogg.library import service as library_service
from backlogg.library.schemas import LibraryEntryIn, LibraryStatusOut
from backlogg.ratings import service as ratings_service
from backlogg.ratings.schemas import RatingIn, RatingListOut, RatingOut
from backlogg.users.auth import get_current_user, get_current_user_optional
from backlogg.users.models import User

router = APIRouter(prefix="/books", tags=["books"])


@router.get(
    "",
    response_model=BookListOut,
    summary="List books",
    description="Paginated list of catalogued books (no external fallback); genre filter + sort.",
)
async def list_books(
    genre: str | None = Query(default=None, description="Filter by genre slug"),
    sort: BookSortEnum = Query(default=BookSortEnum.rating_desc, description="Sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_books(db, genre=genre, sort=sort, page=page, limit=limit)


@router.get(
    "/{slug}/similar",
    response_model=SimilarBooksOut,
    summary="Similar books",
    description=(
        "Up to 10 similar books computed locally: same-author matches (feature 19) "
        "take priority over genre overlap. No external API calls."
    ),
)
async def get_similar_books(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_similar_books(db, slug)


@router.get(
    "/{slug}/ratings",
    response_model=RatingListOut,
    summary="List book ratings",
    description="Public, paginated ratings & reviews for a book, newest first.",
)
async def list_book_ratings(
    slug: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.list_item_ratings(
        db,
        item_type="BOOK",
        slug=slug,
        page=page,
        limit=limit,
        caller_id=current_user.id if current_user else None,
    )


@router.put(
    "/{slug}/rating",
    response_model=RatingOut,
    summary="Rate a book",
    description="Upsert the caller's score/review (full replace); recomputes aggregates. Auth.",
)
async def rate_book(
    slug: str,
    payload: RatingIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await ratings_service.rate_item(
        db, item_type="BOOK", slug=slug, payload=payload, user=current_user
    )


@router.delete(
    "/{slug}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete own book rating",
    description="Remove the caller's rating and recompute aggregates. Requires auth.",
)
async def delete_book_rating(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ratings_service.delete_item_rating(db, item_type="BOOK", slug=slug, user=current_user)


@router.put(
    "/{slug}/library",
    response_model=LibraryStatusOut,
    summary="Set book library status",
    description="Upsert the caller's backlog status for this book. Requires auth.",
)
async def set_book_library(
    slug: str,
    payload: LibraryEntryIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await library_service.set_library_status(
        db, item_type="BOOK", slug=slug, status=payload.status, user=current_user
    )


@router.delete(
    "/{slug}/library",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove book from library",
    description="Delete the caller's library entry for this book. Requires auth.",
)
async def delete_book_library(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await library_service.remove_library_entry(db, item_type="BOOK", slug=slug, user=current_user)


@router.get(
    "/{slug}",
    response_model=BookOut,
    summary="Get book detail",
    description="Full book detail; on-demand Open Library fallback. Auth optional (viewer_status).",
)
async def get_book(
    slug: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    viewer_id = current_user.id if current_user else None
    return await service.get_book(db, slug, viewer_id=viewer_id)
