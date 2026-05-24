import re

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.series import repository as repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.models import Series
from backlogg.shared.external_ids import upsert_external_id

_tmdb = TMDBSeriesClient()


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-2005``) and replaces hyphens
    with spaces so the string can be used as a TMDB search query.
    """
    # Remove trailing 4-digit year suffix
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


async def get_series(db: AsyncSession, slug: str) -> Series:
    # 1. Look up in local DB
    series = await repo.get_series_by_slug(db, slug)
    if series:
        return series

    # 2. Derive a search title from the slug and query TMDB
    query = _title_from_slug(slug)
    search_result = await _tmdb.search_series(query)
    if search_result is None:
        raise HTTPException(status_code=404, detail="Series not found")

    # 3. Fetch full detail from TMDB (includes genres, seasons, etc.)
    tmdb_id = search_result["id"]
    detail = await _tmdb.get_series_detail(tmdb_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Series not found")

    # 4. Persist to local DB via repository
    series_data = _tmdb.series_to_dict(detail)
    series = await repo.upsert_series(db, series_data)

    # 5. Persist the TMDB external ID
    await upsert_external_id(db, "SERIES", series.id, "TMDB", str(tmdb_id))
    await db.commit()

    return series
