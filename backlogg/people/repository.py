from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.books.models import Book
from backlogg.movies.models import Movie
from backlogg.people.schemas import CreditOut, PersonOut
from backlogg.series.models import Series
from backlogg.shared.external_ids import upsert_external_id
from backlogg.shared.models import Credit, Person
from backlogg.shared.slugs import external_id_slug


async def get_person_by_slug(db: AsyncSession, slug: str) -> PersonOut | None:
    """Return a PersonOut with resolved credit item_slug/item_title, or None."""
    result = await db.execute(
        select(Person).where(Person.slug == slug).options(selectinload(Person.credits))
    )
    person = result.scalar_one_or_none()
    if person is None:
        return None

    credits_out = await _resolve_credits(db, person.credits)

    return PersonOut(
        id=person.id,
        name=person.name,
        slug=person.slug,
        profile_url=person.profile_url,
        credits=credits_out,
    )


async def _resolve_credits(db: AsyncSession, credits: list[Credit]) -> list[CreditOut]:
    """Resolve item_slug and item_title for each credit by joining relevant tables."""
    # Gather item IDs by type
    movie_ids: list[int] = []
    series_ids: list[int] = []
    book_ids: list[int] = []
    for credit in credits:
        if credit.item_type == "MOVIE":
            movie_ids.append(credit.item_id)
        elif credit.item_type == "SERIES":
            series_ids.append(credit.item_id)
        elif credit.item_type == "BOOK":
            book_ids.append(credit.item_id)

    # Fetch movies in bulk
    movies_by_id: dict[int, Movie] = {}
    if movie_ids:
        movie_result = await db.execute(select(Movie).where(Movie.id.in_(movie_ids)))
        for movie in movie_result.scalars().all():
            movies_by_id[movie.id] = movie

    # Fetch series in bulk
    series_by_id: dict[int, Series] = {}
    if series_ids:
        series_result = await db.execute(select(Series).where(Series.id.in_(series_ids)))
        for series in series_result.scalars().all():
            series_by_id[series.id] = series

    # Fetch books in bulk
    books_by_id: dict[int, Book] = {}
    if book_ids:
        book_result = await db.execute(select(Book).where(Book.id.in_(book_ids)))
        for book in book_result.scalars().all():
            books_by_id[book.id] = book

    credits_out: list[CreditOut] = []
    for credit in credits:
        item_slug: str | None = None
        item_title: str | None = None

        if credit.item_type == "MOVIE":
            movie = movies_by_id.get(credit.item_id)
            if movie:
                item_slug = movie.slug
                item_title = movie.title
        elif credit.item_type == "SERIES":
            series = series_by_id.get(credit.item_id)
            if series:
                item_slug = series.slug
                item_title = series.title
        elif credit.item_type == "BOOK":
            book = books_by_id.get(credit.item_id)
            if book:
                item_slug = book.slug
                item_title = book.title

        credits_out.append(
            CreditOut(
                item_type=credit.item_type,
                item_id=credit.item_id,
                item_slug=item_slug,
                item_title=item_title,
                role=credit.role,
                character_name=credit.character_name,
                billing_order=credit.billing_order,
            )
        )

    return credits_out


async def get_person_id_by_external(db: AsyncSession, source: str, external_id: str) -> int | None:
    """Return the person.id linked to a given external ID, or None."""
    from backlogg.shared.external_ids import ExternalId  # avoid circular import

    result = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == "PERSON",
            ExternalId.source == source,
            ExternalId.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def get_person_by_id(db: AsyncSession, person_id: int) -> Person | None:
    """Return a Person by primary key, or None."""
    result = await db.execute(select(Person).where(Person.id == person_id))
    return result.scalar_one_or_none()


async def get_or_create_person_by_external(
    db: AsyncSession,
    source: str,
    external_id: str,
    name: str,
    slug: str,
    profile_url: str | None,
    now: datetime,
) -> Person:
    """Resolve a person by their external id, creating the row if unknown.

    The per-item counterpart of the batch person resolution in
    ``backlogg/shared/bulk_load.py``: one lookup by external id, then a
    slug-keyed upsert plus the external-id link when the person is new.
    Looking the external id up first is what stops ``uq_external_id`` from
    blowing up when the same TMDB person shows up under slightly different
    name variants across items.  The lookup is scoped to ``item_type =
    'PERSON'``, which is also the leading column of that constraint since
    migration 0036 (issue #20): a movie or series holding the same TMDB number
    is a different row and must not be mistaken for this person.

    ``slug`` gets the issue #18 fallback applied as a last line of defence: an
    empty slug would upsert on ``uq_people_slug`` and make every caller that
    forgot the fallback collapse its people into a single row, silently
    reattributing credits.  Callers already build the slug with
    ``slug_with_external_fallback``; this only catches the ones that do not.
    """
    slug = slug or external_id_slug(source, external_id)

    existing_id = await get_person_id_by_external(db, source, external_id)
    if existing_id is not None:
        person = await get_person_by_id(db, existing_id)
        if person is not None:
            return person

    person = await upsert_person(
        db,
        {
            "name": name,
            "slug": slug,
            "profile_url": profile_url,
            "last_synced_at": now,
        },
    )
    await upsert_external_id(db, "PERSON", person.id, source, external_id)
    return person


async def upsert_person(db: AsyncSession, data: dict) -> Person:
    """Upsert a person by slug (idempotent).

    ``data`` must contain: name, slug, profile_url, last_synced_at.
    """
    stmt = (
        pg_insert(Person)
        .values(**data)
        .on_conflict_do_update(
            constraint="uq_people_slug",
            set_={
                "name": data["name"],
                "profile_url": data["profile_url"],
                "last_synced_at": data["last_synced_at"],
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(Person.id)
    )
    result = await db.execute(stmt)
    person_id = result.scalar_one()
    await db.flush()

    # Expire any stale cached instance so the SELECT returns the updated row
    for obj in db.identity_map.values():
        if isinstance(obj, Person) and obj.id == person_id:
            db.expire(obj)
            break

    # Reload from DB
    person_result = await db.execute(select(Person).where(Person.id == person_id))
    return person_result.scalar_one()


async def upsert_credit(db: AsyncSession, data: dict) -> Credit:
    """Upsert a credit by (item_type, item_id, person_id, role) (idempotent).

    ``data`` must contain: item_type, item_id, person_id, role,
    and optionally character_name, billing_order.
    """
    stmt = (
        pg_insert(Credit)
        .values(**data)
        .on_conflict_do_update(
            constraint="uq_credit",
            set_={
                "character_name": data.get("character_name"),
                "billing_order": data.get("billing_order"),
            },
        )
        .returning(Credit.id)
    )
    result = await db.execute(stmt)
    credit_id = result.scalar_one()
    await db.flush()

    credit_result = await db.execute(select(Credit).where(Credit.id == credit_id))
    return credit_result.scalar_one()
