from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.movies import repository as repo
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.models import Movie
from backlogg.shared.external_ids import upsert_external_id

_tmdb = TMDBClient()


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-1999``) and replaces hyphens
    with spaces so the string can be used as a TMDB search query.
    """
    import re

    # Remove trailing 4-digit year suffix
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


async def get_movie(db: AsyncSession, slug: str) -> Movie:
    # 1. Look up in local DB
    movie = await repo.get_movie_by_slug(db, slug)
    if movie:
        return movie

    # 2. Derive a search title from the slug and query TMDB
    query = _title_from_slug(slug)
    search_result = await _tmdb.search_movie(query)
    if search_result is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    # 3. Fetch full detail from TMDB (includes genres, runtime, etc.)
    tmdb_id = search_result["id"]
    detail = await _tmdb.get_movie_detail(tmdb_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    # 4. Persist to local DB via repository
    movie_data = _tmdb.movie_to_dict(detail)
    movie = await repo.upsert_movie(db, movie_data)

    # 5. Persist the TMDB external ID
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", str(tmdb_id))
    await db.commit()

    return movie
