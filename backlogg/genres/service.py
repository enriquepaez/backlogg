from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.cache import get_cache
from backlogg.core.config import settings
from backlogg.genres import repository as repo
from backlogg.genres.schemas import GenreListOut, GenreWithCountOut


async def list_genres(
    db: AsyncSession,
    item_type: str | None,
) -> GenreListOut:
    # /genres is an expensive aggregate (per-type item counts) that changes only
    # as the catalog grows. Serve it from the in-process TTL cache on a hit; the
    # cache lives behind get_cache() so it can move to Redis without touching this
    # call site.
    cache = get_cache()
    key = f"genres:{item_type}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    genres: list[GenreWithCountOut] = await repo.list_genres(db, item_type=item_type)
    result = GenreListOut(genres=genres)
    cache.set(key, result, settings.CACHE_TTL_GENRES)
    return result
