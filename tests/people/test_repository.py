"""Tests for backlogg/people/repository.py against real test DB."""

from datetime import UTC, datetime

from backlogg.movies.repository import upsert_movie
from backlogg.people.repository import (
    get_person_by_slug,
    upsert_credit,
    upsert_person,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _person_data(slug: str, name: str = "Test Person") -> dict:
    return {
        "name": name,
        "slug": slug,
        "profile_url": "https://example.com/photo.jpg",
        "last_synced_at": _now(),
    }


async def test_upsert_person_creates(db):
    """Upsert creates a new person record."""
    person = await upsert_person(db, _person_data("test-person-create-001"))
    assert person.id is not None
    assert person.name == "Test Person"
    assert person.slug == "test-person-create-001"
    assert person.profile_url == "https://example.com/photo.jpg"


async def test_upsert_person_idempotent(db):
    """Upserting the same slug twice does not create a duplicate."""
    p1 = await upsert_person(db, _person_data("test-person-idem-001", "Original Name"))
    p2 = await upsert_person(db, _person_data("test-person-idem-001", "Updated Name"))
    assert p1.id == p2.id
    assert p2.name == "Updated Name"


async def test_get_person_by_slug_not_found(db):
    """get_person_by_slug returns None for unknown slug."""
    result = await get_person_by_slug(db, "slug-that-does-not-exist-999abc")
    assert result is None


async def test_get_person_by_slug_found(db):
    """get_person_by_slug returns PersonOut with correct fields."""
    person = await upsert_person(db, _person_data("test-person-found-001", "Jane Doe"))
    result = await get_person_by_slug(db, "test-person-found-001")
    assert result is not None
    assert result.id == person.id
    assert result.name == "Jane Doe"
    assert result.slug == "test-person-found-001"
    assert result.credits == []


async def test_get_person_by_slug_with_credits(db):
    """get_person_by_slug returns PersonOut with resolved credits."""
    from datetime import UTC, datetime

    # Create a movie to reference
    movie = await upsert_movie(
        db,
        {
            "title": "Credit Test Movie",
            "original_title": "Credit Test Movie",
            "slug": "credit-test-movie-2001",
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
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )

    # Create person
    person = await upsert_person(db, _person_data("test-actor-credits-001", "Actor One"))

    # Create credit
    await upsert_credit(
        db,
        {
            "item_type": "MOVIE",
            "item_id": movie.id,
            "person_id": person.id,
            "role": "ACTOR",
            "character_name": "Hero",
            "billing_order": 1,
        },
    )

    result = await get_person_by_slug(db, "test-actor-credits-001")
    assert result is not None
    assert len(result.credits) == 1
    credit = result.credits[0]
    assert credit.item_type == "MOVIE"
    assert credit.item_id == movie.id
    assert credit.item_slug == "credit-test-movie-2001"
    assert credit.item_title == "Credit Test Movie"
    assert credit.role == "ACTOR"
    assert credit.character_name == "Hero"
    assert credit.billing_order == 1


async def test_upsert_credit_idempotent(db):
    """Upserting the same credit (item_type, item_id, person_id, role) is idempotent."""
    person = await upsert_person(db, _person_data("test-director-idem-001", "Director Idem"))
    await upsert_movie(
        db,
        {
            "title": "Director Idem Movie",
            "original_title": "Director Idem Movie",
            "slug": "director-idem-movie-2002",
            "overview": None,
            "release_date": None,
            "runtime": 100,
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
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )
    from backlogg.movies.repository import get_movie_by_slug

    movie = await get_movie_by_slug(db, "director-idem-movie-2002")
    assert movie is not None

    credit_data = {
        "item_type": "MOVIE",
        "item_id": movie.id,
        "person_id": person.id,
        "role": "DIRECTOR",
        "character_name": None,
        "billing_order": None,
    }
    c1 = await upsert_credit(db, credit_data)
    c2 = await upsert_credit(db, credit_data)
    assert c1.id == c2.id


async def test_get_person_by_slug_with_book_credits(db):
    """_resolve_credits handles BOOK item_type correctly."""
    from backlogg.books.repository import upsert_book

    book = await upsert_book(
        db,
        {
            "title": "Author Test Book",
            "original_title": None,
            "slug": "author-test-book-repo-2023",
            "overview": None,
            "first_publish_date": None,
            "original_language": None,
            "poster_url": None,
            "rating_external": None,
            "rating_count_external": None,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": [],
        },
    )

    person = await upsert_person(db, _person_data("test-book-author-001", "Book Author"))
    await upsert_credit(
        db,
        {
            "item_type": "BOOK",
            "item_id": book.id,
            "person_id": person.id,
            "role": "AUTHOR",
            "character_name": None,
            "billing_order": None,
        },
    )

    result = await get_person_by_slug(db, "test-book-author-001")
    assert result is not None
    assert len(result.credits) == 1
    credit = result.credits[0]
    assert credit.item_type == "BOOK"
    assert credit.item_id == book.id
    assert credit.item_slug == "author-test-book-repo-2023"
    assert credit.item_title == "Author Test Book"
    assert credit.role == "AUTHOR"
