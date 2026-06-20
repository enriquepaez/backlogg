from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.books.models import Book, BookGenre, book_genres_join
from backlogg.books.schemas import BookSortEnum


async def list_books(
    db: AsyncSession,
    genre: str | None,
    sort: BookSortEnum,
    page: int,
    limit: int,
) -> tuple[list[Book], int]:
    """Return a paginated list of books with optional genre filter and sorting.

    Sort by first_publish_date for date_desc / date_asc (not release_date).
    Returns a tuple of (items, total_count).
    """
    base_query = select(Book).options(selectinload(Book.genres))

    if genre is not None:
        base_query = base_query.join(Book.genres).where(BookGenre.slug == genre)

    # Count query (without pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Sorting
    if sort == BookSortEnum.rating_desc:
        order_col = Book.rating_external.desc().nulls_last()
    elif sort == BookSortEnum.rating_asc:
        order_col = Book.rating_external.asc().nulls_last()
    elif sort == BookSortEnum.date_desc:
        order_col = Book.first_publish_date.desc().nulls_last()
    elif sort == BookSortEnum.date_asc:
        order_col = Book.first_publish_date.asc().nulls_last()
    else:  # title_asc
        order_col = Book.title.asc()

    base_query = base_query.order_by(order_col).offset((page - 1) * limit).limit(limit)
    result = await db.execute(base_query)
    items = list(result.scalars().unique().all())

    return items, total


async def get_book_by_slug(db: AsyncSession, slug: str) -> Book | None:
    result = await db.execute(
        select(Book).where(Book.slug == slug).options(selectinload(Book.genres))
    )
    return result.scalar_one_or_none()


async def _get_or_create_genre(db: AsyncSession, name: str, slug: str) -> BookGenre:
    stmt = (
        pg_insert(BookGenre)
        .values(name=name, slug=slug)
        .on_conflict_do_update(
            constraint="uq_book_genre_name",
            set_={"slug": slug},
        )
        .returning(BookGenre.id)
    )
    result = await db.execute(stmt)
    genre_id = result.scalar_one()
    await db.flush()
    genre_result = await db.execute(select(BookGenre).where(BookGenre.id == genre_id))
    return genre_result.scalar_one()


async def upsert_book(db: AsyncSession, data: dict) -> Book:
    """Insert or update a book by slug.

    The ``data`` dict must contain all book fields plus an optional
    ``genres`` list of dicts with ``name`` and ``slug`` keys.
    """
    genres_data: list[dict] = data.pop("genres", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    stmt = (
        pg_insert(Book)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={
                k: v
                for k, v in data.items()
                if k not in ("id", "slug", "created_at", "rating_count_internal")
            },
        )
        .returning(Book.id)
    )
    result = await db.execute(stmt)
    book_id = result.scalar_one()
    await db.flush()

    # Expire any cached version of this book so the SELECT below returns
    # the updated row, not the stale identity-map entry.
    for obj in db.identity_map.values():
        if isinstance(obj, Book) and obj.id == book_id:
            db.expire(obj)
            break

    # Reload the full book instance with genres
    book_result = await db.execute(
        select(Book).where(Book.id == book_id).options(selectinload(Book.genres))
    )
    book = book_result.scalar_one()

    # Handle genres: get-or-create each genre and assign to book
    if genres_data:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        # Sync genres via the association table — delete existing and re-insert
        await db.execute(book_genres_join.delete().where(book_genres_join.c.book_id == book_id))
        for genre in genre_objects:
            await db.execute(book_genres_join.insert().values(book_id=book_id, genre_id=genre.id))
        await db.flush()

        # Expire and reload to get fresh genres
        await db.refresh(book, ["genres"])

    return book
