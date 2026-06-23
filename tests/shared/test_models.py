from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backlogg.shared.external_ids import (
    ExternalId,
    get_external_id,
    set_external_id,
    upsert_external_id,
)
from backlogg.shared.models import Credit, Person


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def test_create_person(db):
    """Create a Person and verify all fields are persisted."""
    person = Person(
        name="Christopher Nolan",
        slug="test-model-christopher-nolan",
        profile_url="https://image.tmdb.org/t/p/w500/nolan.jpg",
        last_synced_at=_now(),
    )
    db.add(person)
    await db.flush()

    assert person.id is not None
    assert person.name == "Christopher Nolan"
    assert person.slug == "test-model-christopher-nolan"
    assert person.profile_url == "https://image.tmdb.org/t/p/w500/nolan.jpg"
    assert person.created_at is not None
    assert person.updated_at is not None


async def test_create_credit(db):
    """Create a Credit associated with a Person and verify fields."""
    person = Person(
        name="Cillian Murphy",
        slug="test-model-cillian-murphy",
        last_synced_at=_now(),
    )
    db.add(person)
    await db.flush()

    credit = Credit(
        item_type="MOVIE",
        item_id=12345,
        person_id=person.id,
        role="ACTOR",
        character_name="J. Robert Oppenheimer",
        billing_order=0,
    )
    db.add(credit)
    await db.flush()

    assert credit.id is not None
    assert credit.item_type == "MOVIE"
    assert credit.item_id == 12345
    assert credit.person_id == person.id
    assert credit.role == "ACTOR"
    assert credit.character_name == "J. Robert Oppenheimer"
    assert credit.billing_order == 0
    assert credit.created_at is not None


async def test_credit_unique_constraint(db):
    """Violating uq_credit (item_type, item_id, person_id, role) raises IntegrityError."""
    person = Person(
        name="Tom Hardy",
        slug="tom-hardy",
        last_synced_at=_now(),
    )
    db.add(person)
    await db.flush()

    credit1 = Credit(
        item_type="MOVIE",
        item_id=99001,
        person_id=person.id,
        role="ACTOR",
    )
    db.add(credit1)
    await db.flush()

    credit2 = Credit(
        item_type="MOVIE",
        item_id=99001,
        person_id=person.id,
        role="ACTOR",
    )
    db.add(credit2)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_external_id_crud(db):
    """Test set_external_id, get_external_id, and upsert_external_id helpers."""
    # set
    record = await set_external_id(db, "MOVIE", 1001, "TMDB", "tt0816692")
    assert record.id is not None
    assert record.external_id == "tt0816692"

    # get — should find what was just set
    found = await get_external_id(db, "MOVIE", 1001, "TMDB")
    assert found is not None
    assert found.external_id == "tt0816692"

    # get — non-existing
    missing = await get_external_id(db, "MOVIE", 9999, "TMDB")
    assert missing is None

    # upsert — update existing
    updated = await upsert_external_id(db, "MOVIE", 1001, "TMDB", "tt0816693")
    assert updated.external_id == "tt0816693"


async def test_external_id_unique_constraint(db):
    """Inserting a duplicate (source, external_id) pair raises IntegrityError."""
    await set_external_id(db, "MOVIE", 2001, "TMDB", "unique-ext-1")
    await db.flush()

    # Same source + external_id but different item — should violate uq_external_id
    record2 = ExternalId(
        item_type="SERIES",
        item_id=2002,
        source="TMDB",
        external_id="unique-ext-1",
    )
    db.add(record2)
    with pytest.raises(IntegrityError):
        await db.flush()
