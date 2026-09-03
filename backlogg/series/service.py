import re
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.library import service as library_service
from backlogg.people import repository as people_repo
from backlogg.series import repository as repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient, _slugify
from backlogg.series.models import Series
from backlogg.series.schemas import (
    SeriesGenreOut,
    SeriesListItemOut,
    SeriesListOut,
    SeriesOut,
    SeriesSortEnum,
    SimilarSeriesListOut,
    SimilarSeriesOut,
)
from backlogg.shared.bulk_load import BulkPerson
from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import get_external_id, upsert_external_id
from backlogg.shared.models import Person
from backlogg.shared.rating_sort import rating_desc_sort_key

_tmdb = TMDBSeriesClient()

_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def _title_from_slug(slug: str) -> str:
    """Extract a searchable title from a slug.

    Strips the trailing year suffix (e.g. ``-2005``) and replaces hyphens
    with spaces so the string can be used as a TMDB search query.
    """
    # Remove trailing 4-digit year suffix
    title = re.sub(r"-\d{4}$", "", slug)
    return title.replace("-", " ")


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


async def collect_series_credits(tmdb_id: int) -> list[BulkPerson]:
    """Fetch a series' credits from TMDB and map them to bulk credit rows.

    Cast only (top 10 by billing order): the credits endpoint carries no
    meaningful directors for TV, and creators come from the detail payload's
    ``created_by`` instead — see ``collect_series_creators``.  Split out for
    feature 84 so the batch write path can gather a whole slice's people
    before touching the database.
    """
    credits_data = await _tmdb.get_series_credits(tmdb_id)
    if not credits_data:
        return []

    rows: list[BulkPerson] = []
    for member in credits_data.get("cast", [])[:10]:
        row = _tmdb_person_row(
            member,
            "ACTOR",
            character_name=member.get("character") or None,
            billing_order=member.get("order"),
        )
        if row is not None:
            rows.append(row)
    return rows


def collect_series_creators(created_by: list) -> list[BulkPerson]:
    """Map a series detail's ``created_by`` entries to CREATOR credit rows."""
    rows: list[BulkPerson] = []
    for member in created_by or []:
        row = _tmdb_person_row(member, "CREATOR")
        if row is not None:
            rows.append(row)
    return rows


async def _persist_series_credit_rows(
    db: AsyncSession, series: Series, rows: list[BulkPerson]
) -> None:
    """Persist already-mapped credit rows one person at a time."""
    now = datetime.now(UTC)

    for row in rows:
        person = await _get_or_create_person_tmdb(
            db, int(row.external_id), row.name, row.slug, row.profile_url, now
        )
        if person is None:
            continue

        await people_repo.upsert_credit(
            db,
            {
                "item_type": "SERIES",
                "item_id": series.id,
                "person_id": person.id,
                "role": row.role,
                "character_name": row.character_name,
                "billing_order": row.billing_order,
            },
        )


async def _persist_series_people(db: AsyncSession, series: Series, tmdb_id: int) -> None:
    """Fetch credits from TMDB and persist people + credits for a series.

    On-demand route only — feature 84 leaves the single-item path writing one
    person at a time on purpose; the nightly/backfill route batches instead.
    """
    await _persist_series_credit_rows(db, series, await collect_series_credits(tmdb_id))


async def _persist_series_creators(db: AsyncSession, series: Series, created_by: list) -> None:
    """Persist creators (CREATOR role) from the series created_by field."""
    await _persist_series_credit_rows(db, series, collect_series_creators(created_by))


async def list_series(
    db: AsyncSession,
    genre: str | None,
    sort: SeriesSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters,
) -> SeriesListOut:
    items, total = await repo.list_series(
        db, genre=genre, sort=sort, page=page, limit=limit, filters=filters
    )
    list_items = [
        SeriesListItemOut(
            id=s.id,
            title=s.title,
            slug=s.slug,
            poster_url=s.poster_url,
            release_date=s.first_air_date,
            rating_external=float(s.rating_external) if s.rating_external is not None else None,
            rating_internal=float(s.rating_internal) if s.rating_internal is not None else None,
            genres=[g.slug for g in s.genres],
        )
        for s in items
    ]
    return SeriesListOut(items=list_items, total=total, page=page, limit=limit)


async def get_series(db: AsyncSession, slug: str, viewer_id: int | None = None) -> SeriesOut:
    # 1. Look up in local DB
    series = await repo.get_series_by_slug(db, slug)
    if series is None:
        # 2. Derive a search title from the slug and query TMDB
        query = _title_from_slug(slug)
        search_results = await _tmdb.search_series(query)
        search_result = search_results[0] if search_results else None
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

        # 6. Persist people (cast + creators) and their credits
        await _persist_series_people(db, series, tmdb_id)
        created_by = detail.get("created_by", [])
        if created_by:
            await _persist_series_creators(db, series, created_by)

        await db.commit()

    credits = await get_credits_for_item(db, "SERIES", series.id)
    viewer_status = await library_service.get_viewer_status(db, "SERIES", series.id, viewer_id)
    return SeriesOut(
        id=series.id,
        title=series.title,
        original_title=series.original_title,
        slug=series.slug,
        overview=series.overview,
        first_air_date=series.first_air_date,
        last_air_date=series.last_air_date,
        number_of_seasons=series.number_of_seasons,
        number_of_episodes=series.number_of_episodes,
        status=series.status,
        original_language=series.original_language,
        poster_url=series.poster_url,
        backdrop_url=series.backdrop_url,
        rating_external=(
            float(series.rating_external) if series.rating_external is not None else None
        ),
        rating_count_external=series.rating_count_external,
        rating_internal=(
            float(series.rating_internal) if series.rating_internal is not None else None
        ),
        rating_count_internal=series.rating_count_internal,
        genres=[SeriesGenreOut(id=g.id, name=g.name, slug=g.slug) for g in series.genres],
        credits=credits,
        viewer_status=viewer_status,
    )


async def get_similar_series(db: AsyncSession, slug: str) -> SimilarSeriesListOut:
    # 1. Look up the source series — 404 if it doesn't exist
    series = await repo.get_series_by_slug(db, slug)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    # 2. Get the TMDB ID for the source series
    ext_id = await get_external_id(db, "SERIES", series.id, "TMDB")
    if ext_id is None:
        # Series exists locally but has no TMDB ID — return empty results
        return SimilarSeriesListOut(results=[])

    tmdb_id = int(ext_id.external_id)

    # 3. Fetch recommendations from TMDB (page 1 only)
    raw_results = await _tmdb.get_series_recommendations(tmdb_id)

    # 4. Persist any new series and collect up to 10 results. TMDB's
    # recommendations order reflects its own relevance ranking, not rating —
    # results are re-sorted below by rating_internal desc / rating_external
    # desc tie-break (feature 66) so the community's own rating decides what
    # the user sees first, not TMDB's ordering or rating_external.
    results: list[tuple[float | None, float | None, SimilarSeriesOut]] = []
    for raw in raw_results[:10]:
        rec_tmdb_id = raw.get("id")
        if not rec_tmdb_id:
            continue

        # Build slug from recommendation data (list endpoint format, not detail)
        title = raw.get("name", "")
        first_air_date_str = raw.get("first_air_date", "")
        release_date = None
        year = ""
        if first_air_date_str:
            try:
                release_date = date.fromisoformat(first_air_date_str)
                year = str(release_date.year)
            except ValueError:
                pass

        slug_base = _slugify(title)
        rec_slug = f"{slug_base}-{year}" if year else slug_base

        # Try local DB first
        rec_series = await repo.get_series_by_slug(db, rec_slug)
        if rec_series is None:
            # Fetch full detail and persist
            detail = await _tmdb.get_series_detail(rec_tmdb_id)
            if detail is None:
                continue
            series_data = _tmdb.series_to_dict(detail)
            rec_series = await repo.upsert_series(db, series_data)
            await upsert_external_id(db, "SERIES", rec_series.id, "TMDB", str(rec_tmdb_id))

            # Persist people (cast + creators) — the row was just created by
            # the upsert above (feature 70: this path previously left
            # recommended series without credits forever, since upsert_series
            # is idempotent by slug and this branch only runs once per series).
            await _persist_series_people(db, rec_series, rec_tmdb_id)
            rec_created_by = detail.get("created_by", [])
            if rec_created_by:
                await _persist_series_creators(db, rec_series, rec_created_by)

            await db.commit()

        rating_internal = (
            float(rec_series.rating_internal) if rec_series.rating_internal is not None else None
        )
        rating_external = (
            float(rec_series.rating_external) if rec_series.rating_external is not None else None
        )
        results.append(
            (
                rating_internal,
                rating_external,
                SimilarSeriesOut(
                    title=rec_series.title,
                    slug=rec_series.slug,
                    poster_url=rec_series.poster_url,
                    release_date=rec_series.first_air_date,
                    rating_external=rating_external,
                    rating_internal=rating_internal,
                ),
            )
        )

    ordered = sorted(results, key=lambda r: rating_desc_sort_key(r[0], r[1]))
    return SimilarSeriesListOut(results=[out for _, _, out in ordered])
