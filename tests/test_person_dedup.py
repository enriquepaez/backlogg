"""Tests for person deduplication by external ID.

These tests verify that when the same external person (TMDB or Open Library)
appears across multiple items, the service reuses the existing Person record
instead of creating a new one, avoiding IntegrityError on uq_external_id.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from backlogg.books import repository as books_repo
from backlogg.books import service as books_service
from backlogg.books.service import _persist_book_authors
from backlogg.movies import repository as movies_repo
from backlogg.movies import service as movies_service
from backlogg.movies.service import _persist_movie_people
from backlogg.people import repository as people_repo
from backlogg.series import repository as series_repo
from backlogg.series import service as series_service
from backlogg.series.service import _persist_series_creators, _persist_series_people
from backlogg.shared.external_ids import get_external_id, upsert_external_id
from backlogg.shared.models import Credit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _movie_data(slug: str, title: str = "Dedup Test Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "release_date": None,
        "runtime": 90,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
    }


def _series_data(slug: str, title: str = "Dedup Test Series") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "first_air_date": None,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
    }


def _book_data(slug: str, title: str = "Dedup Test Book") -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": None,
        "first_publish_date": None,
        "original_language": None,
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
    }


def _credits_response(tmdb_person_id: int, name: str) -> dict:
    """Build a minimal TMDB credits response with one actor."""
    return {
        "cast": [
            {
                "id": tmdb_person_id,
                "name": name,
                "profile_path": None,
                "character": "Hero",
                "order": 0,
            }
        ],
        "crew": [],
    }


def _work_detail_with_author(author_olid: str) -> dict:
    return {
        "key": f"/works/OLDEDUP{author_olid}W",
        "title": "Dedup Book",
        "authors": [{"author": {"key": f"/authors/{author_olid}"}}],
    }


# ---------------------------------------------------------------------------
# People repository helpers
# ---------------------------------------------------------------------------


async def test_get_person_id_by_external_returns_none_when_not_found(db):
    """get_person_id_by_external returns None for an unknown external ID."""
    result = await people_repo.get_person_id_by_external(db, "TMDB", "999999999")
    assert result is None


async def test_get_person_id_by_external_returns_id_when_found(db):
    """get_person_id_by_external returns the person.id after registering an external ID."""
    person = await people_repo.upsert_person(
        db,
        {
            "name": "Dedup Actor Repo",
            "slug": "dedup-actor-repo-001",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )
    await upsert_external_id(db, "PERSON", person.id, "TMDB", "DEDUP_TMDB_REPO_001")

    found_id = await people_repo.get_person_id_by_external(db, "TMDB", "DEDUP_TMDB_REPO_001")
    assert found_id == person.id


async def test_get_person_by_id_returns_person(db):
    """get_person_by_id returns the correct Person record."""
    person = await people_repo.upsert_person(
        db,
        {
            "name": "Dedup Actor ById",
            "slug": "dedup-actor-by-id-001",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )
    found = await people_repo.get_person_by_id(db, person.id)
    assert found is not None
    assert found.id == person.id
    assert found.name == "Dedup Actor ById"


async def test_get_person_by_id_returns_none_for_unknown(db):
    """get_person_by_id returns None for a non-existent primary key."""
    found = await people_repo.get_person_by_id(db, 999999999)
    assert found is None


# ---------------------------------------------------------------------------
# Movie deduplication
# ---------------------------------------------------------------------------


async def test_persist_movie_people_dedup_same_actor_two_movies(db):
    """Same TMDB actor in two movies reuses the existing Person without IntegrityError.

    Scenario:
      - Movie A is persisted with actor TMDB ID 77001 named "Actor Variant A".
      - Movie B is persisted with the SAME TMDB ID 77001 but name "Actor Variant B".
    Expected:
      - Only one Person row exists.
      - Credits for both movies point to the same person.id.
    """
    TMDB_PERSON_ID = 77001

    movie_a = await movies_repo.upsert_movie(db, _movie_data("dedup-movie-a-2024"))
    movie_b = await movies_repo.upsert_movie(db, _movie_data("dedup-movie-b-2024", "Dedup Movie B"))

    credits_a = _credits_response(TMDB_PERSON_ID, "Actor Variant A")
    credits_b = _credits_response(TMDB_PERSON_ID, "Actor Variant B")

    with patch.object(
        movies_service._tmdb,
        "get_movie_credits",
        new_callable=AsyncMock,
        return_value=credits_a,
    ):
        await _persist_movie_people(db, movie_a, 1001)

    with patch.object(
        movies_service._tmdb,
        "get_movie_credits",
        new_callable=AsyncMock,
        return_value=credits_b,
    ):
        # Must NOT raise IntegrityError
        await _persist_movie_people(db, movie_b, 1002)

    # Only one Person linked to TMDB ID 77001
    person_id = await people_repo.get_person_id_by_external(db, "TMDB", str(TMDB_PERSON_ID))
    assert person_id is not None

    # Both movies have a credit pointing to the same person
    result = await db.execute(
        select(Credit).where(
            Credit.person_id == person_id,
            Credit.item_type == "MOVIE",
        )
    )
    credits_list = result.scalars().all()
    item_ids = {c.item_id for c in credits_list}
    assert movie_a.id in item_ids
    assert movie_b.id in item_ids


async def test_persist_movie_people_creates_external_id_on_first_insert(db):
    """First time a TMDB actor is persisted, an external_id row is created."""
    TMDB_PERSON_ID = 77002

    movie = await movies_repo.upsert_movie(db, _movie_data("dedup-movie-c-2024"))
    credits_data = _credits_response(TMDB_PERSON_ID, "New Actor C")

    with patch.object(
        movies_service._tmdb,
        "get_movie_credits",
        new_callable=AsyncMock,
        return_value=credits_data,
    ):
        await _persist_movie_people(db, movie, 1003)

    person_id = await people_repo.get_person_id_by_external(db, "TMDB", str(TMDB_PERSON_ID))
    assert person_id is not None

    person = await people_repo.get_person_by_id(db, person_id)
    assert person is not None
    assert person.name == "New Actor C"

    ext = await get_external_id(db, "PERSON", person_id, "TMDB")
    assert ext is not None
    assert ext.external_id == str(TMDB_PERSON_ID)


async def test_persist_movie_people_dedup_director_same_tmdb_id(db):
    """Same TMDB director in two movies reuses the existing Person without IntegrityError."""
    TMDB_DIRECTOR_ID = 77003

    movie_a = await movies_repo.upsert_movie(db, _movie_data("dedup-dir-movie-a-2024"))
    movie_b = await movies_repo.upsert_movie(
        db, _movie_data("dedup-dir-movie-b-2024", "Dedup Director Movie B")
    )

    def _director_credits(name: str) -> dict:
        return {
            "cast": [],
            "crew": [
                {
                    "id": TMDB_DIRECTOR_ID,
                    "name": name,
                    "profile_path": None,
                    "job": "Director",
                }
            ],
        }

    with patch.object(
        movies_service._tmdb,
        "get_movie_credits",
        new_callable=AsyncMock,
        return_value=_director_credits("Director Name A"),
    ):
        await _persist_movie_people(db, movie_a, 1004)

    with patch.object(
        movies_service._tmdb,
        "get_movie_credits",
        new_callable=AsyncMock,
        return_value=_director_credits("Director Name B"),
    ):
        await _persist_movie_people(db, movie_b, 1005)

    person_id = await people_repo.get_person_id_by_external(db, "TMDB", str(TMDB_DIRECTOR_ID))
    assert person_id is not None

    result = await db.execute(
        select(Credit).where(
            Credit.person_id == person_id,
            Credit.item_type == "MOVIE",
            Credit.role == "DIRECTOR",
        )
    )
    director_credits = result.scalars().all()
    item_ids = {c.item_id for c in director_credits}
    assert movie_a.id in item_ids
    assert movie_b.id in item_ids


# ---------------------------------------------------------------------------
# Series deduplication
# ---------------------------------------------------------------------------


async def test_persist_series_people_dedup_same_actor_two_series(db):
    """Same TMDB actor in two series reuses the existing Person without IntegrityError."""
    TMDB_PERSON_ID = 88001

    series_a = await series_repo.upsert_series(db, _series_data("dedup-series-a-2024"))
    series_b = await series_repo.upsert_series(
        db, _series_data("dedup-series-b-2024", "Dedup Series B")
    )

    credits_a = _credits_response(TMDB_PERSON_ID, "Series Actor Variant A")
    credits_b = _credits_response(TMDB_PERSON_ID, "Series Actor Variant B")

    with patch.object(
        series_service._tmdb,
        "get_series_credits",
        new_callable=AsyncMock,
        return_value=credits_a,
    ):
        await _persist_series_people(db, series_a, 2001)

    with patch.object(
        series_service._tmdb,
        "get_series_credits",
        new_callable=AsyncMock,
        return_value=credits_b,
    ):
        await _persist_series_people(db, series_b, 2002)

    person_id = await people_repo.get_person_id_by_external(db, "TMDB", str(TMDB_PERSON_ID))
    assert person_id is not None

    result = await db.execute(
        select(Credit).where(
            Credit.person_id == person_id,
            Credit.item_type == "SERIES",
        )
    )
    credits_list = result.scalars().all()
    item_ids = {c.item_id for c in credits_list}
    assert series_a.id in item_ids
    assert series_b.id in item_ids


async def test_persist_series_creators_dedup_same_creator_two_series(db):
    """Same TMDB creator in two series reuses the existing Person without IntegrityError."""
    TMDB_CREATOR_ID = 88002

    series_a = await series_repo.upsert_series(db, _series_data("dedup-creator-series-a-2024"))
    series_b = await series_repo.upsert_series(
        db, _series_data("dedup-creator-series-b-2024", "Dedup Creator Series B")
    )

    def _created_by(name: str) -> list:
        return [{"id": TMDB_CREATOR_ID, "name": name, "profile_path": None}]

    await _persist_series_creators(db, series_a, _created_by("Creator Variant A"))
    # Must NOT raise IntegrityError
    await _persist_series_creators(db, series_b, _created_by("Creator Variant B"))

    person_id = await people_repo.get_person_id_by_external(db, "TMDB", str(TMDB_CREATOR_ID))
    assert person_id is not None

    result = await db.execute(
        select(Credit).where(
            Credit.person_id == person_id,
            Credit.item_type == "SERIES",
            Credit.role == "CREATOR",
        )
    )
    credits_list = result.scalars().all()
    item_ids = {c.item_id for c in credits_list}
    assert series_a.id in item_ids
    assert series_b.id in item_ids


# ---------------------------------------------------------------------------
# Books (Open Library) deduplication
# ---------------------------------------------------------------------------


async def test_persist_book_authors_dedup_same_author_two_books(db):
    """Same OL author in two books reuses the existing Person without IntegrityError."""
    OL_AUTHOR_ID = "OLDEDUP88003A"

    book_a = await books_repo.upsert_book(db, _book_data("dedup-book-a-2024"))
    book_b = await books_repo.upsert_book(db, _book_data("dedup-book-b-2024", "Dedup Book B"))

    work_detail_a = _work_detail_with_author(OL_AUTHOR_ID)
    work_detail_b = _work_detail_with_author(OL_AUTHOR_ID)

    author_data_a = {
        "key": f"/authors/{OL_AUTHOR_ID}",
        "name": "OL Author Variant A",
        "personal_name": "OL Author Variant A Full",
    }
    author_data_b = {
        "key": f"/authors/{OL_AUTHOR_ID}",
        "name": "OL Author Variant B",
        "personal_name": "OL Author Variant B Full",
    }

    with patch.object(
        books_service._ol_client,
        "get_author",
        new_callable=AsyncMock,
        return_value=author_data_a,
    ):
        await _persist_book_authors(db, book_a, work_detail_a)

    with patch.object(
        books_service._ol_client,
        "get_author",
        new_callable=AsyncMock,
        return_value=author_data_b,
    ):
        # Must NOT raise IntegrityError
        await _persist_book_authors(db, book_b, work_detail_b)

    person_id = await people_repo.get_person_id_by_external(db, "OPEN_LIBRARY", OL_AUTHOR_ID)
    assert person_id is not None

    result = await db.execute(
        select(Credit).where(
            Credit.person_id == person_id,
            Credit.item_type == "BOOK",
            Credit.role == "AUTHOR",
        )
    )
    credits_list = result.scalars().all()
    item_ids = {c.item_id for c in credits_list}
    assert book_a.id in item_ids
    assert book_b.id in item_ids


async def test_persist_book_authors_creates_external_id_on_first_insert(db):
    """First time an OL author is persisted, an external_id row is created."""
    OL_AUTHOR_ID = "OLDEDUP88004A"

    book = await books_repo.upsert_book(db, _book_data("dedup-book-c-2024"))
    work_detail = _work_detail_with_author(OL_AUTHOR_ID)
    author_data = {
        "key": f"/authors/{OL_AUTHOR_ID}",
        "name": "OL New Author D",
    }

    with patch.object(
        books_service._ol_client,
        "get_author",
        new_callable=AsyncMock,
        return_value=author_data,
    ):
        await _persist_book_authors(db, book, work_detail)

    person_id = await people_repo.get_person_id_by_external(db, "OPEN_LIBRARY", OL_AUTHOR_ID)
    assert person_id is not None

    ext = await get_external_id(db, "PERSON", person_id, "OPEN_LIBRARY")
    assert ext is not None
    assert ext.external_id == OL_AUTHOR_ID


# ---------------------------------------------------------------------------
# upsert_external_id idempotency and conflict guard
# ---------------------------------------------------------------------------


async def test_upsert_external_id_same_source_external_id_different_item_no_error(db):
    """upsert_external_id with duplicate (source, external_id) but different item_id
    does NOT raise IntegrityError and returns the first (winning) row."""
    person_a = await people_repo.upsert_person(
        db,
        {
            "name": "Conflict Person A",
            "slug": "conflict-person-a-001",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )
    person_b = await people_repo.upsert_person(
        db,
        {
            "name": "Conflict Person B",
            "slug": "conflict-person-b-001",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )

    first_row = await upsert_external_id(db, "PERSON", person_a.id, "TMDB", "CONFLICT_EXT_001")
    assert first_row is not None
    assert first_row.item_id == person_a.id

    # Second call with same (source, external_id) but different item_id must not raise.
    second_row = await upsert_external_id(db, "PERSON", person_b.id, "TMDB", "CONFLICT_EXT_001")
    assert second_row is not None
    # First claim wins — item_id must still point to person_a.
    assert second_row.item_id == person_a.id


async def test_upsert_external_id_same_source_external_id_same_item_is_idempotent(db):
    """upsert_external_id called twice with the same (source, external_id, item_id)
    returns the existing row without error (idempotent)."""
    person = await people_repo.upsert_person(
        db,
        {
            "name": "Idempotent Person",
            "slug": "idempotent-person-001",
            "profile_url": None,
            "last_synced_at": _now(),
        },
    )

    first_row = await upsert_external_id(db, "PERSON", person.id, "TMDB", "IDEM_EXT_001")
    assert first_row is not None

    # Second call — must not raise and must return the same row.
    second_row = await upsert_external_id(db, "PERSON", person.id, "TMDB", "IDEM_EXT_001")
    assert second_row is not None
    assert second_row.id == first_row.id
    assert second_row.item_id == person.id
    assert second_row.external_id == "IDEM_EXT_001"
