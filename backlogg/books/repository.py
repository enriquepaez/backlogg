from sqlalchemy import case, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.books.models import Book, BookGenre, book_genres_join
from backlogg.books.schemas import BookSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters, build_catalog_filter_clauses
from backlogg.shared.models import Credit


async def list_books(
    db: AsyncSession,
    genre: str | None,
    sort: BookSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters | None = None,
) -> tuple[list[Book], int]:
    """Return a paginated list of books with optional genre/search/date/rating filters and sorting.

    Sort by first_publish_date for date_desc / date_asc (not release_date). ``filters``
    (feature 50) holds ``search``/``date_from``/``date_to``/``rating_internal_min``/
    ``rating_internal_max``/``rating_external_min``/``rating_external_max`` — all
    independently optional and AND-combined with ``genre``. Returns a tuple of
    (items, total_count).
    """
    base_query = select(Book).options(selectinload(Book.genres))

    if genre is not None:
        base_query = base_query.join(Book.genres).where(BookGenre.slug == genre)

    if filters is not None:
        clauses = build_catalog_filter_clauses(
            filters,
            title_col=Book.title,
            date_col=Book.first_publish_date,
            rating_internal_col=Book.rating_internal,
            rating_external_col=Book.rating_external,
        )
        if clauses:
            base_query = base_query.where(*clauses)

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
    """Get or create a genre, treating the slug as its real identity.

    Open Library subjects are not canonical: two spellings of the same genre
    (e.g. "Fiction" / "fiction") slugify to the same value.  Looking the slug
    up first reuses the existing row instead of violating
    ``uq_book_genre_slug`` — the slug is what the app exposes in
    ``?genre=<slug>`` filters.  The name-conflict upsert remains as a
    fallback for the same name arriving with a slug not yet in the table.
    """
    result = await db.execute(select(BookGenre).where(BookGenre.slug == slug))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

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

    Per-field admin locks (feature 49 — catalog_manual_edit): any column
    listed in the existing row's ``locked_fields`` is excluded from the
    UPDATE, via a CASE per column inside the ON CONFLICT DO UPDATE statement
    that keeps the target row's own value when it is locked instead of the
    proposed (``excluded``) value. ``genres`` is not a plain column, so it is
    checked separately after the reload below, skipping the genre re-sync
    block when locked.
    """
    genres_data: list[dict] = data.pop("genres", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    insert_stmt = pg_insert(Book).values(**data)
    set_ = {
        k: case(
            (Book.locked_fields.contains([k]), getattr(Book, k)),
            else_=getattr(insert_stmt.excluded, k),
        )
        for k in data
        if k not in ("id", "slug", "created_at", "rating_count_internal")
    }
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_=set_,
    ).returning(Book.id)
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

    # Handle genres: get-or-create each genre and assign to book.
    # Deduplicate by slug first — two subjects of the same book that slugify
    # to the same value must map to a single genre row and a single join row.
    if genres_data and "genres" not in book.locked_fields:
        genre_objects = []
        seen_slugs: set[str] = set()
        for g in genres_data:
            if g["slug"] in seen_slugs:
                continue
            seen_slugs.add(g["slug"])
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


async def admin_update_book(db: AsyncSession, book: Book, updates: dict) -> Book:
    """Apply an admin backoffice edit (feature 49) to ``book`` in place.

    ``updates`` keys are a subset of the editable scalar columns (``title``,
    ``poster_url``, ``first_publish_date``) plus an optional ``genres`` key
    holding a list of ``{"name", "slug"}`` dicts already resolved by the
    caller — same shape as ``upsert_book``'s ``genres_data``, so it reuses
    the same get-or-create + re-sync logic (deduplicated by slug). Locked-
    fields bookkeeping is the caller's responsibility
    (backlogg/admin/service.py), not this function's.
    """
    genres_data = updates.pop("genres", None)

    for key, value in updates.items():
        setattr(book, key, value)

    if genres_data is not None:
        genre_objects = []
        seen_slugs: set[str] = set()
        for g in genres_data:
            if g["slug"] in seen_slugs:
                continue
            seen_slugs.add(g["slug"])
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        await db.execute(book_genres_join.delete().where(book_genres_join.c.book_id == book.id))
        for genre in genre_objects:
            await db.execute(book_genres_join.insert().values(book_id=book.id, genre_id=genre.id))
        await db.flush()
        await db.refresh(book, ["genres"])

    await db.flush()
    return book


async def get_author_person_ids(db: AsyncSession, book_id: int) -> list[int]:
    """Return the person IDs credited as AUTHOR for a given book (feature 19)."""
    result = await db.execute(
        select(Credit.person_id).where(
            Credit.item_type == "BOOK",
            Credit.item_id == book_id,
            Credit.role == "AUTHOR",
        )
    )
    return [row[0] for row in result.all()]


async def get_books_by_same_authors(
    db: AsyncSession,
    person_ids: list[int],
    exclude_book_id: int,
    limit: int,
) -> list[Book]:
    """Return other books credited to any of ``person_ids`` as AUTHOR.

    Excludes the source book itself. Ordered by ``rating_external`` descending
    (the tie-break used across all "similar" priority tiers).
    """
    if not person_ids:
        return []

    stmt = (
        select(Book)
        .join(Credit, (Credit.item_id == Book.id) & (Credit.item_type == "BOOK"))
        .where(
            Credit.role == "AUTHOR",
            Credit.person_id.in_(person_ids),
            Book.id != exclude_book_id,
        )
        .options(selectinload(Book.genres))
        .distinct()
        .order_by(Book.rating_external.desc().nulls_last())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


async def get_books_by_genre_overlap(
    db: AsyncSession,
    book_id: int,
    genre_ids: list[int],
    exclude_book_ids: set[int],
    limit: int,
) -> list[Book]:
    """Return books sharing at least one genre with ``genre_ids``.

    Excludes the source book and anything already picked by the caller
    (e.g. author matches). Ordered by number of shared genres descending,
    then ``rating_external`` descending.
    """
    if not genre_ids:
        return []

    excluded = set(exclude_book_ids) | {book_id}
    overlap = func.count(book_genres_join.c.genre_id).label("overlap")

    stmt = (
        select(Book, overlap)
        .join(book_genres_join, book_genres_join.c.book_id == Book.id)
        .where(book_genres_join.c.genre_id.in_(genre_ids))
        .where(Book.id.notin_(excluded) if excluded else literal(True))
        .options(selectinload(Book.genres))
        .group_by(Book.id)
        .order_by(overlap.desc(), Book.rating_external.desc().nulls_last())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]
