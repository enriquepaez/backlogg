from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.movies.models import Movie, MovieGenre, movie_genres_join
from backlogg.movies.schemas import MovieSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters, build_catalog_filter_clauses


async def list_movies(
    db: AsyncSession,
    genre: str | None,
    sort: MovieSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters | None = None,
) -> tuple[list[Movie], int]:
    """Return a paginated list of movies with optional genre/search/date/rating filters and sorting.

    ``filters`` (feature 50) holds ``search``/``date_from``/``date_to``/
    ``rating_internal_min``/``rating_internal_max``/``rating_external_min``/
    ``rating_external_max`` — all independently optional and AND-combined
    with ``genre``. Returns a tuple of (items, total_count).
    """
    base_query = select(Movie).options(selectinload(Movie.genres))

    if genre is not None:
        base_query = base_query.join(Movie.genres).where(MovieGenre.slug == genre)

    if filters is not None:
        clauses = build_catalog_filter_clauses(
            filters,
            title_col=Movie.title,
            date_col=Movie.release_date,
            rating_internal_col=Movie.rating_internal,
            rating_external_col=Movie.rating_external,
        )
        if clauses:
            base_query = base_query.where(*clauses)

    # Count query (without pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Sorting. rating_desc/rating_asc order by rating_internal (the community's
    # own rating, feature 66) first — rating_external is only an internal
    # tie-break for items whose rating_internal is still NULL or tied, never
    # the primary/visible sort criterion.
    if sort == MovieSortEnum.rating_desc:
        order_cols = (
            Movie.rating_internal.desc().nulls_last(),
            Movie.rating_external.desc().nulls_last(),
        )
    elif sort == MovieSortEnum.rating_asc:
        order_cols = (
            Movie.rating_internal.asc().nulls_last(),
            Movie.rating_external.desc().nulls_last(),
        )
    elif sort == MovieSortEnum.date_desc:
        order_cols = (Movie.release_date.desc().nulls_last(),)
    elif sort == MovieSortEnum.date_asc:
        order_cols = (Movie.release_date.asc().nulls_last(),)
    else:  # title_asc
        order_cols = (Movie.title.asc(),)

    base_query = base_query.order_by(*order_cols).offset((page - 1) * limit).limit(limit)
    result = await db.execute(base_query)
    items = list(result.scalars().unique().all())

    return items, total


async def get_movie_by_slug(db: AsyncSession, slug: str) -> Movie | None:
    result = await db.execute(
        select(Movie).where(Movie.slug == slug).options(selectinload(Movie.genres))
    )
    return result.scalar_one_or_none()


async def _get_or_create_genre(db: AsyncSession, name: str, slug: str) -> MovieGenre:
    result = await db.execute(select(MovieGenre).where(MovieGenre.slug == slug))
    genre = result.scalar_one_or_none()
    if genre is None:
        genre = MovieGenre(name=name, slug=slug)
        db.add(genre)
        await db.flush()
    return genre


async def upsert_movie(db: AsyncSession, data: dict) -> Movie:
    """Insert or update a movie by slug.

    The ``data`` dict must contain all movie fields plus an optional
    ``genres`` list of dicts with ``name`` and ``slug`` keys.

    Per-field admin locks (feature 49 — catalog_manual_edit): any column
    listed in the existing row's ``locked_fields`` is excluded from the
    UPDATE, via a CASE per column inside the ON CONFLICT DO UPDATE statement
    that keeps the target row's own value when it is locked instead of the
    proposed (``excluded``) value. ``genres`` is not a plain column, so it is
    checked separately after the reload below, skipping the genre re-sync
    block when locked.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    genres_data: list[dict] = data.pop("genres", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    insert_stmt = pg_insert(Movie).values(**data)
    set_ = {
        k: case(
            (Movie.locked_fields.contains([k]), getattr(Movie, k)),
            else_=getattr(insert_stmt.excluded, k),
        )
        for k in data
        if k not in ("id", "slug", "created_at", "rating_count_internal")
    }
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_=set_,
    ).returning(Movie.id)
    result = await db.execute(stmt)
    movie_id = result.scalar_one()
    await db.flush()

    # Expire any cached version of this movie so the SELECT below returns
    # the updated row, not the stale identity-map entry.
    for obj in db.identity_map.values():
        if isinstance(obj, Movie) and obj.id == movie_id:
            db.expire(obj)
            break

    # Reload the full movie instance with genres
    movie_result = await db.execute(
        select(Movie).where(Movie.id == movie_id).options(selectinload(Movie.genres))
    )
    movie = movie_result.scalar_one()

    # Handle genres: get-or-create each genre and assign to movie
    if genres_data and "genres" not in movie.locked_fields:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        # Sync genres via the association table — delete existing and re-insert
        await db.execute(movie_genres_join.delete().where(movie_genres_join.c.movie_id == movie_id))
        for genre in genre_objects:
            await db.execute(
                movie_genres_join.insert().values(movie_id=movie_id, genre_id=genre.id)
            )
        await db.flush()

        # Expire and reload to get fresh genres
        await db.refresh(movie, ["genres"])

    return movie


async def admin_update_movie(db: AsyncSession, movie: Movie, updates: dict) -> Movie:
    """Apply an admin backoffice edit (feature 49) to ``movie`` in place.

    ``updates`` keys are a subset of the editable scalar columns (``title``,
    ``poster_url``, ``release_date``) plus an optional ``genres`` key holding
    a list of ``{"name", "slug"}`` dicts already resolved by the caller —
    same shape as ``upsert_movie``'s ``genres_data``, so it reuses the same
    get-or-create + re-sync logic. Locked-fields bookkeeping is the caller's
    responsibility (backlogg/admin/service.py), not this function's.
    """
    genres_data = updates.pop("genres", None)

    for key, value in updates.items():
        setattr(movie, key, value)

    if genres_data is not None:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        await db.execute(movie_genres_join.delete().where(movie_genres_join.c.movie_id == movie.id))
        for genre in genre_objects:
            await db.execute(
                movie_genres_join.insert().values(movie_id=movie.id, genre_id=genre.id)
            )
        await db.flush()
        await db.refresh(movie, ["genres"])

    await db.flush()
    return movie
