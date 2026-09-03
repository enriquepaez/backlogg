import re
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.library import service as library_service
from backlogg.movies import repository as repo
from backlogg.movies.adapters.tmdb import TMDBClient, _slugify
from backlogg.movies.models import Movie
from backlogg.movies.schemas import (
    GenreOut,
    MovieListItemOut,
    MovieListOut,
    MovieOut,
    MovieSortEnum,
    SimilarMovieOut,
    SimilarMoviesOut,
)
from backlogg.people import repository as people_repo
from backlogg.shared.bulk_load import BulkPerson
from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import get_external_id, upsert_external_id
from backlogg.shared.models import Person

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


def _year_from_slug(slug: str) -> int | None:
    """Extract the 4-digit year suffix from a slug, or None if absent."""
    m = re.search(r"-(\d{4})$", slug)
    return int(m.group(1)) if m else None


async def _get_or_create_person_tmdb(
    db: AsyncSession,
    tmdb_person_id: int,
    name: str,
    slug: str,
    profile_url: str | None,
    now: datetime,
) -> Person | None:
    """Look up a person by TMDB ID; create one if not found.

    Returns the Person instance, or None if the lookup/creation fails.
    Avoids IntegrityError on uq_external_id when the same TMDB person
    appears across multiple items with slightly different name variants.
    """
    return await people_repo.get_or_create_person_by_external(
        db, "TMDB", str(tmdb_person_id), name, slug, profile_url, now
    )


def _tmdb_person_row(
    member: dict,
    role: str,
    character_name: str | None = None,
    billing_order: int | None = None,
) -> BulkPerson | None:
    """Map one TMDB cast/crew member to a ``BulkPerson``, or None if unusable."""
    person_tmdb_id = member.get("id")
    if not person_tmdb_id:
        return None

    name = member.get("name", "")
    if not name:
        return None

    profile_path = member.get("profile_path")
    return BulkPerson(
        source="TMDB",
        external_id=str(person_tmdb_id),
        name=name,
        slug=_slugify(name),
        profile_url=f"{_TMDB_IMAGE_BASE}{profile_path}" if profile_path else None,
        role=role,
        character_name=character_name,
        billing_order=billing_order,
    )


def map_movie_credits(credits_data: dict | None) -> list[BulkPerson]:
    """Map an already-fetched TMDB credits payload to bulk credit rows.

    Pure mapping, no network: the top-10 billed cast and every director,
    exactly the selection ``_persist_movie_people`` has always persisted.
    Split out from ``collect_movie_credits`` for feature 86, whose seeding
    path gets this very payload embedded in the detail response
    (``/movie/{id}?append_to_response=credits,external_ids``) and must not
    spend a second request to re-fetch it.  Mirrors
    ``backlogg.series.service.map_series_cast``.
    """
    if not credits_data:
        return []

    rows: list[BulkPerson] = []
    # Cast — top 10 actors by billing order
    for member in credits_data.get("cast", [])[:10]:
        row = _tmdb_person_row(
            member,
            "ACTOR",
            character_name=member.get("character") or None,
            billing_order=member.get("order"),
        )
        if row is not None:
            rows.append(row)

    # Crew — directors only
    for member in credits_data.get("crew", []):
        if member.get("job") != "Director":
            continue
        row = _tmdb_person_row(member, "DIRECTOR")
        if row is not None:
            rows.append(row)

    return rows


async def collect_movie_credits(tmdb_id: int) -> list[BulkPerson]:
    """Fetch a movie's credits from TMDB and map them to bulk credit rows.

    One network call plus ``map_movie_credits``.  This is the route the
    on-demand paths use (``GET /movies/{slug}``, ``/similar``, the search
    fan-out) and the one the targeted credits backfill uses, where the item
    row already exists and only its credits are missing.  The seeding path
    does **not** call it: it already holds the payload from the detail
    response and calls ``map_movie_credits`` directly.
    """
    return map_movie_credits(await _tmdb.get_movie_credits(tmdb_id))


async def _persist_movie_people(db: AsyncSession, movie: Movie, tmdb_id: int) -> None:
    """Fetch credits from TMDB and persist people + credits for a movie.

    The on-demand route (``GET /movies/{slug}``, ``/similar``) keeps writing
    one person at a time: it only ever handles a single item, so batching
    would buy nothing (feature 84 leaves this path untouched on purpose).
    """
    now = datetime.now(UTC)

    for row in await collect_movie_credits(tmdb_id):
        person = await _get_or_create_person_tmdb(
            db, int(row.external_id), row.name, row.slug, row.profile_url, now
        )
        if person is None:
            continue

        await people_repo.upsert_credit(
            db,
            {
                "item_type": "MOVIE",
                "item_id": movie.id,
                "person_id": person.id,
                "role": row.role,
                "character_name": row.character_name,
                "billing_order": row.billing_order,
            },
        )


async def list_movies(
    db: AsyncSession,
    genre: str | None,
    sort: MovieSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters,
) -> MovieListOut:
    items, total = await repo.list_movies(
        db, genre=genre, sort=sort, page=page, limit=limit, filters=filters
    )
    list_items = [
        MovieListItemOut(
            id=m.id,
            title=m.title,
            slug=m.slug,
            poster_url=m.poster_url,
            release_date=m.release_date,
            rating_external=float(m.rating_external) if m.rating_external is not None else None,
            rating_internal=float(m.rating_internal) if m.rating_internal is not None else None,
            genres=[g.slug for g in m.genres],
        )
        for m in items
    ]
    return MovieListOut(items=list_items, total=total, page=page, limit=limit)


async def get_movie(db: AsyncSession, slug: str, viewer_id: int | None = None) -> MovieOut:
    # 1. Look up in local DB
    movie = await repo.get_movie_by_slug(db, slug)
    if movie is None:
        # 2. Derive a search title and optional year from the slug and query TMDB
        query = _title_from_slug(slug)
        year = _year_from_slug(slug)
        search_results = await _tmdb.search_movie(query, year=year)
        search_result = search_results[0] if search_results else None
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

    credits = await get_credits_for_item(db, "MOVIE", movie.id)
    viewer_status = await library_service.get_viewer_status(db, "MOVIE", movie.id, viewer_id)
    return MovieOut(
        id=movie.id,
        title=movie.title,
        original_title=movie.original_title,
        slug=movie.slug,
        overview=movie.overview,
        release_date=movie.release_date,
        runtime=movie.runtime,
        original_language=movie.original_language,
        poster_url=movie.poster_url,
        backdrop_url=movie.backdrop_url,
        budget=movie.budget,
        revenue=movie.revenue,
        status=movie.status,
        rating_external=float(movie.rating_external) if movie.rating_external is not None else None,
        rating_count_external=movie.rating_count_external,
        rating_internal=(
            float(movie.rating_internal) if movie.rating_internal is not None else None
        ),
        rating_count_internal=movie.rating_count_internal,
        genres=[GenreOut(id=g.id, name=g.name, slug=g.slug) for g in movie.genres],
        credits=credits,
        viewer_status=viewer_status,
    )


async def get_similar_movies(db: AsyncSession, slug: str) -> SimilarMoviesOut:
    # 1. Look up the source movie — 404 if it doesn't exist
    movie = await repo.get_movie_by_slug(db, slug)
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    # 2. Get the TMDB ID for the source movie
    ext_id = await get_external_id(db, "MOVIE", movie.id, "TMDB")
    if ext_id is None:
        # Movie exists locally but has no TMDB ID — return empty results
        return SimilarMoviesOut(results=[])

    tmdb_id = int(ext_id.external_id)

    # 3. Fetch recommendations from TMDB (page 1 only)
    raw_results = await _tmdb.get_movie_recommendations(tmdb_id)

    # 4. Persist any new movies and collect up to 10 results
    results: list[SimilarMovieOut] = []
    for raw in raw_results[:10]:
        rec_tmdb_id = raw.get("id")
        if not rec_tmdb_id:
            continue

        # Build slug from recommendation data (list endpoint format, not detail)
        title = raw.get("title", "")
        release_date_str = raw.get("release_date", "")
        release_date = None
        year = ""
        if release_date_str:
            try:
                release_date = date.fromisoformat(release_date_str)
                year = str(release_date.year)
            except ValueError:
                pass

        slug_base = _slugify(title)
        rec_slug = f"{slug_base}-{year}" if year else slug_base

        # Try local DB first
        rec_movie = await repo.get_movie_by_slug(db, rec_slug)
        if rec_movie is None:
            # Fetch full detail and persist
            detail = await _tmdb.get_movie_detail(rec_tmdb_id)
            if detail is None:
                continue
            movie_data = _tmdb.movie_to_dict(detail)
            rec_movie = await repo.upsert_movie(db, movie_data)
            await upsert_external_id(db, "MOVIE", rec_movie.id, "TMDB", str(rec_tmdb_id))

            # Persist people (cast + directors) — the row was just created by
            # the upsert above (feature 70: this path previously left
            # recommended movies without credits forever, since upsert_movie
            # is idempotent by slug and this branch only runs once per movie).
            await _persist_movie_people(db, rec_movie, rec_tmdb_id)

            await db.commit()

        results.append(
            SimilarMovieOut(
                title=rec_movie.title,
                slug=rec_movie.slug,
                poster_url=rec_movie.poster_url,
                release_date=rec_movie.release_date,
                rating_external=(
                    float(rec_movie.rating_external)
                    if rec_movie.rating_external is not None
                    else None
                ),
                rating_internal=(
                    float(rec_movie.rating_internal)
                    if rec_movie.rating_internal is not None
                    else None
                ),
            )
        )

    return SimilarMoviesOut(results=results)
