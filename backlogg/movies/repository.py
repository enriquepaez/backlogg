from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.movies.models import Movie, MovieGenre, movie_genres_join
from backlogg.movies.schemas import MovieSortEnum


async def list_movies(
    db: AsyncSession,
    genre: str | None,
    sort: MovieSortEnum,
    page: int,
    limit: int,
) -> tuple[list[Movie], int]:
    """Return a paginated list of movies with optional genre filter and sorting.

    Returns a tuple of (items, total_count).
    """
    base_query = select(Movie).options(selectinload(Movie.genres))

    if genre is not None:
        base_query = base_query.join(Movie.genres).where(MovieGenre.slug == genre)

    # Count query (without pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Sorting
    if sort == MovieSortEnum.rating_desc:
        order_col = Movie.rating_external.desc().nulls_last()
    elif sort == MovieSortEnum.rating_asc:
        order_col = Movie.rating_external.asc().nulls_last()
    elif sort == MovieSortEnum.date_desc:
        order_col = Movie.release_date.desc().nulls_last()
    elif sort == MovieSortEnum.date_asc:
        order_col = Movie.release_date.asc().nulls_last()
    else:  # title_asc
        order_col = Movie.title.asc()

    base_query = base_query.order_by(order_col).offset((page - 1) * limit).limit(limit)
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
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    genres_data: list[dict] = data.pop("genres", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    stmt = (
        pg_insert(Movie)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={
                k: v
                for k, v in data.items()
                if k not in ("id", "slug", "created_at", "rating_count_internal")
            },
        )
        .returning(Movie.id)
    )
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
    if genres_data:
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
