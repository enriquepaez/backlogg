import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.people import repository as people_repo
from backlogg.series import repository as repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient, _slugify
from backlogg.series.models import Series
from backlogg.series.schemas import SeriesListItemOut, SeriesListOut, SeriesSortEnum
from backlogg.shared.external_ids import upsert_external_id

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


async def _persist_series_people(db: AsyncSession, series: Series, tmdb_id: int) -> None:
    """Fetch credits from TMDB and persist people + credits for a series."""
    credits_data = await _tmdb.get_series_credits(tmdb_id)
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
                "item_type": "SERIES",
                "item_id": series.id,
                "person_id": person.id,
                "role": "ACTOR",
                "character_name": member.get("character") or None,
                "billing_order": member.get("order"),
            },
        )

    # Crew — creators from series detail (created_by field in series detail response)
    # Note: series detail includes created_by, but credits endpoint may not.
    # We handle created_by from the series detail separately via the series_detail dict.
    # Here we handle crew from the credits endpoint (directors are rare in TV, so we skip).
    # created_by is handled in get_series by passing detail to this function via a different path.
    # For simplicity, creators are handled via created_by field when available.


async def _persist_series_creators(db: AsyncSession, series: Series, created_by: list) -> None:
    """Persist creators (CREATOR role) from the series created_by field."""
    now = datetime.now(UTC)

    for member in created_by:
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
                "item_type": "SERIES",
                "item_id": series.id,
                "person_id": person.id,
                "role": "CREATOR",
                "character_name": None,
                "billing_order": None,
            },
        )


async def list_series(
    db: AsyncSession,
    genre: str | None,
    sort: SeriesSortEnum,
    page: int,
    limit: int,
) -> SeriesListOut:
    items, total = await repo.list_series(db, genre=genre, sort=sort, page=page, limit=limit)
    list_items = [
        SeriesListItemOut(
            id=s.id,
            title=s.title,
            slug=s.slug,
            poster_url=s.poster_url,
            release_date=s.first_air_date,
            rating_external=float(s.rating_external) if s.rating_external is not None else None,
            genres=[g.slug for g in s.genres],
        )
        for s in items
    ]
    return SeriesListOut(items=list_items, total=total, page=page, limit=limit)


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

    # 6. Persist people (cast + creators) and their credits
    await _persist_series_people(db, series, tmdb_id)
    created_by = detail.get("created_by", [])
    if created_by:
        await _persist_series_creators(db, series, created_by)

    await db.commit()

    return series
