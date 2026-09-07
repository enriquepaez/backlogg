from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError

from backlogg.shared.codes import CREDIT_ROLE_CODES, ITEM_TYPE_CODES
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
    """Create a Credit associated with a Person and verify fields.

    Feature 89: a credit is now exactly ``(item_id, person_id, item_type,
    role)`` plus ``created_at`` — no surrogate ``id``, no ``character_name``,
    no ``billing_order`` — and the two vocabulary columns are ``smallint`` on
    disk while staying strings in Python (``backlogg/shared/codes.py``).
    """
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
        role="DIRECTOR",
    )
    db.add(credit)
    await db.flush()

    assert credit.item_type == "MOVIE"
    assert credit.item_id == 12345
    assert credit.person_id == person.id
    assert credit.role == "DIRECTOR"
    assert credit.created_at is not None

    # Narrow on disk, wide in Python: the row is two smallints.
    stored = (
        await db.execute(
            text("SELECT item_type, role FROM credits WHERE item_id = 12345"),
        )
    ).one()
    assert stored == (ITEM_TYPE_CODES["MOVIE"], CREDIT_ROLE_CODES["DIRECTOR"])


async def test_credit_primary_key_constraint(db):
    """The natural key is the primary key now: a duplicate raises."""
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
        role="DIRECTOR",
    )
    db.add(credit1)
    await db.flush()

    credit2 = Credit(
        item_type="MOVIE",
        item_id=99001,
        person_id=person.id,
        role="DIRECTOR",
    )
    db.add(credit2)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_credit_rejects_an_unknown_role(db):
    """An out-of-vocabulary role raises instead of being silently coerced."""
    person = Person(
        name="Unknown Role Person",
        slug="test-model-unknown-role",
        last_synced_at=_now(),
    )
    db.add(person)
    await db.flush()

    db.add(
        Credit(
            item_type="MOVIE",
            item_id=99002,
            person_id=person.id,
            role="GAFFER",
        )
    )
    with pytest.raises(StatementError, match="unknown credit role"):
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
    """Two items of the *same* type may not share (source, external_id)."""
    await set_external_id(db, "MOVIE", 2001, "TMDB", "unique-ext-1")
    await db.flush()

    # Same item_type + source + external_id, different item — violates
    # uq_external_id. This is a genuinely duplicated id and must still fail.
    record2 = ExternalId(
        item_type="MOVIE",
        item_id=2002,
        source="TMDB",
        external_id="unique-ext-1",
    )
    db.add(record2)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_external_id_is_unique_per_item_type_not_globally(db):
    """The same external id in two different item types is legal (issue #20).

    TMDB numbers movies, series and people in independent sequences that
    overlap, so id 110531 is both a series and an actor. ``uq_external_id``
    used to be ``UNIQUE (source, external_id)`` and the first claimant blocked
    every other type forever; it now carries ``item_type``.
    """
    await set_external_id(db, "SERIES", 2101, "TMDB", "unique-ext-shared-1")
    await set_external_id(db, "PERSON", 2102, "TMDB", "unique-ext-shared-1")
    await set_external_id(db, "MOVIE", 2103, "TMDB", "unique-ext-shared-1")
    await db.flush()

    for item_type, item_id in (("SERIES", 2101), ("PERSON", 2102), ("MOVIE", 2103)):
        found = await get_external_id(db, item_type, item_id, "TMDB")
        assert found is not None
        assert found.external_id == "unique-ext-shared-1"


async def test_upsert_external_id_person_does_not_block_a_series(db):
    """Reproduces issue #20 exactly as it was measured on the dev database.

    A PERSON row holding TMDB id 110531 made the *series* 110531 unlinkable:
    ``upsert_external_id`` pre-checked ``(source, external_id)``, found the
    person, and returned it — no exception, no counter, no log. 7 of the 752
    enumerated 2022 series were lost that way.
    """
    person_link = await upsert_external_id(db, "PERSON", 2201, "TMDB", "110531")
    assert person_link.item_type == "PERSON"
    assert person_link.item_id == 2201

    series_link = await upsert_external_id(db, "SERIES", 2202, "TMDB", "110531")
    assert series_link.item_type == "SERIES"
    assert series_link.item_id == 2202
    assert series_link.id != person_link.id

    # Both links survive and resolve to their own item.
    assert (await get_external_id(db, "PERSON", 2201, "TMDB")).external_id == "110531"
    assert (await get_external_id(db, "SERIES", 2202, "TMDB")).external_id == "110531"


async def test_upsert_external_id_keeps_first_claim_within_a_type(db):
    """Within one item type the pre-check still lets the first claim win.

    Two different series cannot hold the same TMDB id, so the second caller
    gets the existing row back instead of an IntegrityError.
    """
    first = await upsert_external_id(db, "SERIES", 2301, "TMDB", "unique-ext-claim-1")
    second = await upsert_external_id(db, "SERIES", 2302, "TMDB", "unique-ext-claim-1")

    assert second.id == first.id
    assert second.item_id == 2301
    assert await get_external_id(db, "SERIES", 2302, "TMDB") is None
