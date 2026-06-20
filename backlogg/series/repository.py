from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.series.models import Series, SeriesGenre, series_genres_join
from backlogg.series.schemas import SeriesSortEnum


async def list_series(
    db: AsyncSession,
    genre: str | None,
    sort: SeriesSortEnum,
    page: int,
    limit: int,
) -> tuple[list[Series], int]:
    """Return a paginated list of series with optional genre filter and sorting.

    Sort by first_air_date for date_desc / date_asc (not release_date).
    Returns a tuple of (items, total_count).
    """
    base_query = select(Series).options(selectinload(Series.genres))

    if genre is not None:
        base_query = base_query.join(Series.genres).where(SeriesGenre.slug == genre)

    # Count query (without pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Sorting
    if sort == SeriesSortEnum.rating_desc:
        order_col = Series.rating_external.desc().nulls_last()
    elif sort == SeriesSortEnum.rating_asc:
        order_col = Series.rating_external.asc().nulls_last()
    elif sort == SeriesSortEnum.date_desc:
        order_col = Series.first_air_date.desc().nulls_last()
    elif sort == SeriesSortEnum.date_asc:
        order_col = Series.first_air_date.asc().nulls_last()
    else:  # title_asc
        order_col = Series.title.asc()

    base_query = base_query.order_by(order_col).offset((page - 1) * limit).limit(limit)
    result = await db.execute(base_query)
    items = list(result.scalars().unique().all())

    return items, total


async def get_series_by_slug(db: AsyncSession, slug: str) -> Series | None:
    result = await db.execute(
        select(Series).where(Series.slug == slug).options(selectinload(Series.genres))
    )
    return result.scalar_one_or_none()


async def _get_or_create_genre(db: AsyncSession, name: str, slug: str) -> SeriesGenre:
    result = await db.execute(select(SeriesGenre).where(SeriesGenre.slug == slug))
    genre = result.scalar_one_or_none()
    if genre is None:
        genre = SeriesGenre(name=name, slug=slug)
        db.add(genre)
        await db.flush()
    return genre


async def upsert_series(db: AsyncSession, data: dict) -> Series:
    """Insert or update a series by slug.

    The ``data`` dict must contain all series fields plus an optional
    ``genres`` list of dicts with ``name`` and ``slug`` keys.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    genres_data: list[dict] = data.pop("genres", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    stmt = (
        pg_insert(Series)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={
                k: v
                for k, v in data.items()
                if k not in ("id", "slug", "created_at", "rating_count_internal")
            },
        )
        .returning(Series.id)
    )
    result = await db.execute(stmt)
    series_id = result.scalar_one()
    await db.flush()

    # Expire any cached version of this series so the SELECT below returns
    # the updated row, not the stale identity-map entry.
    for obj in db.identity_map.values():
        if isinstance(obj, Series) and obj.id == series_id:
            db.expire(obj)
            break

    # Reload the full series instance with genres
    series_result = await db.execute(
        select(Series).where(Series.id == series_id).options(selectinload(Series.genres))
    )
    series = series_result.scalar_one()

    # Handle genres: get-or-create each genre and assign to series
    if genres_data:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        # Sync genres via the association table — delete existing and re-insert
        await db.execute(
            series_genres_join.delete().where(series_genres_join.c.series_id == series_id)
        )
        for genre in genre_objects:
            await db.execute(
                series_genres_join.insert().values(series_id=series_id, genre_id=genre.id)
            )
        await db.flush()

        # Expire and reload to get fresh genres
        await db.refresh(series, ["genres"])

    return series
