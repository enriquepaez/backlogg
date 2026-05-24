import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.movies import repository as repo
from backlogg.movies.adapters.tmdb import TMDBClient, _slugify
from backlogg.movies.models import Movie
from backlogg.people import repository as people_repo
from backlogg.shared.external_ids import upsert_external_id

_tmdb = TMDBClient()

_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-1999``) and replaces hyphens
    with spaces so the string can be used as a TMDB search query.
    """
    # Remove trailing 4-digit year suffix
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


async def _persist_movie_people(db: AsyncSession, movie: Movie, tmdb_id: int) -> None:
    """Fetch credits from TMDB and persist people + credits for a movie."""
    credits_data = await _tmdb.get_movie_credits(tmdb_id)
    if not credits_data:
        return

    now = datetime.now(UTC)

    # Cast — top 10 actors by billing order
    for member in credits_data.get("cast", [])[:10]:
        person_tmdb_id = member.get("id")
        if not person_tmdb_id:
            continue

        name = member.get("name", "")
        if not name:
            continue

        slug = _slugify(name)
        profile_path = member.get("profile_path")
        profile_url = f"{_TMDB_IMAGE_BASE}{profile_path}" if profile_path else None

        person = await people_repo.upsert_person(
            db,
            {
                "name": name,
                "slug": slug,
                "profile_url": profile_url,
                "last_synced_at": now,
            },
        )
        await upsert_external_id(db, "PERSON", person.id, "TMDB", str(person_tmdb_id))
        await people_repo.upsert_credit(
            db,
            {
                "item_type": "MOVIE",
                "item_id": movie.id,
                "person_id": person.id,
                "role": "ACTOR",
                "character_name": member.get("character") or None,
                "billing_order": member.get("order"),
            },
        )

    # Crew — directors only
    for member in credits_data.get("crew", []):
        if member.get("job") != "Director":
            continue

        person_tmdb_id = member.get("id")
        if not person_tmdb_id:
            continue

        name = member.get("name", "")
        if not name:
            continue

        slug = _slugify(name)
        profile_path = member.get("profile_path")
        profile_url = f"{_TMDB_IMAGE_BASE}{profile_path}" if profile_path else None

        person = await people_repo.upsert_person(
            db,
            {
                "name": name,
                "slug": slug,
                "profile_url": profile_url,
                "last_synced_at": now,
            },
        )
        await upsert_external_id(db, "PERSON", person.id, "TMDB", str(person_tmdb_id))
        await people_repo.upsert_credit(
            db,
            {
                "item_type": "MOVIE",
                "item_id": movie.id,
                "person_id": person.id,
                "role": "DIRECTOR",
                "character_name": None,
                "billing_order": None,
            },
        )


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

    # 6. Persist people (cast + directors) and their credits
    await _persist_movie_people(db, movie, tmdb_id)

    await db.commit()

    return movie
