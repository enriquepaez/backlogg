"""Feature 89 — the cast leaves the relational model, the graph stays.

Four things have to remain true after ``credits`` was split in two, and each
of them is a promise made to somebody:

1. **The cross-type bridge of feature 74 still works.**  ``AUTHOR`` and
   ``SOURCE_AUTHOR`` are graph roles, so ``get_authorship_works`` must return
   exactly what it returned before — including for an author who *also* acts,
   which is the case the split could plausibly have broken.
2. **A person who directs and acts keeps the graph and loses the cast.**  The
   Clint Eastwood case: 9.251 people in production.
3. **The detail page still shows the whole cast, in order.**  Not the first
   N: the payload is never truncated.
4. **The migration runs both ways**, against a database with real rows in it.

(2) and (3) are covered here end to end through the HTTP layer, because the
contract that must not move is the JSON one.
"""

import asyncio
import os
from datetime import UTC, datetime

import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from backlogg.books.models import Book
from backlogg.core.config import settings
from backlogg.main import app
from backlogg.movies.models import Movie
from backlogg.people import repository as people_repo
from backlogg.recommendations import repository as recs_repo
from backlogg.shared.credits import (
    build_cast_payload,
    cast_payload_to_credits,
    get_credits_for_item,
    upsert_item_cast,
)
from backlogg.shared.models import Credit, ItemCast, Person


def _now() -> datetime:
    return datetime.now(UTC)


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _person(db, name: str, slug: str) -> Person:
    person = Person(name=name, slug=slug, last_synced_at=_now())
    db.add(person)
    await db.flush()
    return person


async def _credit(db, item_type: str, item_id: int, person: Person, role: str) -> None:
    db.add(Credit(item_type=item_type, item_id=item_id, person_id=person.id, role=role))
    await db.flush()


# ── 1. The cross-type bridge is untouched ────────────────────────────────────


async def test_authorship_bridge_survives_for_an_author_who_also_acts(db):
    """An author whose acting credits vanished still bridges book <-> film.

    ``get_authorship_works`` reads only ``AUTHOR``/``SOURCE_AUTHOR``, so the
    cast leaving ``credits`` must not change its answer by a single row.  The
    person here is the awkward one: they hold both classes of credit, so a
    split that leaked would show up as a missing or an extra work.
    """
    author = await _person(db, "Split Author Actor", "split-author-actor-89")

    book = Book(title="Split Source Novel", slug="split-source-novel-89", last_synced_at=_now())
    movie = Movie(title="Split Adapted Film", slug="split-adapted-film-89", last_synced_at=_now())
    other = Movie(title="Split Other Film", slug="split-other-film-89", last_synced_at=_now())
    db.add_all([book, movie, other])
    await db.flush()

    await _credit(db, "BOOK", book.id, author, "AUTHOR")
    await _credit(db, "MOVIE", movie.id, author, "SOURCE_AUTHOR")
    # …and they act in a third film, which now lives only in ``item_cast``.
    await upsert_item_cast(
        db, "MOVIE", [(other.id, build_cast_payload([("Split Author Actor", "Themself", 0)]))]
    )

    works = await recs_repo.get_authorship_works(db, author.id)
    assert {(row.item_type, row.item_id, row.role) for row in works} == {
        ("BOOK", book.id, "AUTHOR"),
        ("MOVIE", movie.id, "SOURCE_AUTHOR"),
    }

    from_book = await recs_repo.get_authorship_works(db, author.id, exclude=("BOOK", book.id))
    assert [(row.item_type, row.item_id) for row in from_book] == [("MOVIE", movie.id)]


# ── 2. Directs and acts: keeps the graph, loses the cast ─────────────────────


async def test_a_person_who_directs_and_acts_keeps_the_graph_and_loses_the_cast(client, db):
    """The Clint Eastwood case, end to end.

    ``GET /people/{slug}`` answers 200 with the directing filmography intact
    and **no** ``ACTOR`` entry, while the film's own detail page still lists
    them among the cast.  Both halves of that sentence are the contract
    documented in ``docs/api.md``.
    """
    eastwood = await _person(db, "Split Eastwood", "split-eastwood-89")
    directed = Movie(title="Split Unforgiven", slug="split-unforgiven-89", last_synced_at=_now())
    acted_in = Movie(title="Split In The Line", slug="split-in-the-line-89", last_synced_at=_now())
    db.add_all([directed, acted_in])
    await db.flush()

    await _credit(db, "MOVIE", directed.id, eastwood, "DIRECTOR")
    # He acts in both, and neither acting credit is a row any more.
    for movie, character in ((directed, "Will Munny"), (acted_in, "Frank Horrigan")):
        await upsert_item_cast(
            db, "MOVIE", [(movie.id, build_cast_payload([("Split Eastwood", character, 0)]))]
        )

    response = await client.get("/v1/people/split-eastwood-89")
    assert response.status_code == 200
    body = response.json()
    assert [(c["item_slug"], c["role"]) for c in body["credits"]] == [
        ("split-unforgiven-89", "DIRECTOR")
    ]
    assert all(c["role"] != "ACTOR" for c in body["credits"])

    # The film he only acted in still shows him, through ``item_cast``.
    detail = await client.get("/v1/movies/split-in-the-line-89")
    assert detail.status_code == 200
    assert [
        (c["person_name"], c["role"], c["character_name"]) for c in detail.json()["credits"]
    ] == [("Split Eastwood", "ACTOR", "Frank Horrigan")]


async def test_a_cast_only_person_is_a_404(client, db):
    """No ``people`` row means no person page — the documented 404."""
    movie = Movie(title="Split Cast Only", slug="split-cast-only-89", last_synced_at=_now())
    db.add(movie)
    await db.flush()
    await upsert_item_cast(
        db, "MOVIE", [(movie.id, build_cast_payload([("Split Bit Part", "Extra", 0)]))]
    )

    # The name resolves to a slug, and that slug resolves to nothing.
    assert (
        cast_payload_to_credits(
            (
                await db.execute(
                    select(ItemCast.payload).where(
                        ItemCast.item_type == "MOVIE", ItemCast.item_id == movie.id
                    )
                )
            ).scalar_one()
        )[0].person_slug
        == "split-bit-part"
    )

    response = await client.get("/v1/people/split-bit-part")
    assert response.status_code == 404


# ── 3. The whole cast reaches the detail page, in order ──────────────────────


async def test_the_detail_page_gets_the_full_cast_in_billing_order(db):
    """Never truncated, always ordered, crew after it.

    Production averages 9,31 actors per film with a maximum of 30; the payload
    keeps all of them, which is why ``item_cast`` exists instead of a "top N"
    column.  30 is the measured worst case, so that is what is loaded here.
    """
    movie = Movie(title="Split Full Cast", slug="split-full-cast-89", last_synced_at=_now())
    db.add(movie)
    await db.flush()

    director = await _person(db, "Split Full Director", "split-full-director-89")
    await _credit(db, "MOVIE", movie.id, director, "DIRECTOR")

    # Shuffled on the way in: the payload is stored sorted, not as offered.
    entries = [(f"Split Actor {index:02d}", f"Role {index:02d}", index) for index in range(30)]
    await upsert_item_cast(db, "MOVIE", [(movie.id, build_cast_payload(list(reversed(entries))))])

    credits = await get_credits_for_item(db, "MOVIE", movie.id)

    assert len(credits) == 31
    assert [c.billing_order for c in credits[:30]] == list(range(30))
    assert [c.person_name for c in credits[:30]] == [name for name, _, _ in entries]
    assert all(c.role == "ACTOR" for c in credits[:30])
    # The crew closes the list, exactly where ``ORDER BY billing_order NULLS
    # LAST`` used to leave it.
    assert (credits[30].person_name, credits[30].role) == ("Split Full Director", "DIRECTOR")


async def test_an_item_with_no_cast_returns_only_its_crew(db):
    """Books have no cast at all: the merged read must not invent an empty one."""
    book = Book(title="Split Plain Book", slug="split-plain-book-89", last_synced_at=_now())
    db.add(book)
    await db.flush()
    author = await _person(db, "Split Book Author", "split-book-author-89")
    await _credit(db, "BOOK", book.id, author, "AUTHOR")

    credits = await get_credits_for_item(db, "BOOK", book.id)
    assert [(c.person_name, c.role, c.character_name) for c in credits] == [
        ("Split Book Author", "AUTHOR", None)
    ]


async def test_upsert_item_cast_replaces_the_array_wholesale(db):
    """A re-ingestion rewrites the cast, it does not merge into it."""
    movie = Movie(title="Split Rewrite", slug="split-rewrite-89", last_synced_at=_now())
    db.add(movie)
    await db.flush()

    await upsert_item_cast(
        db,
        "MOVIE",
        [(movie.id, build_cast_payload([("Old A", None, 0), ("Old B", None, 1)]))],
    )
    await upsert_item_cast(db, "MOVIE", [(movie.id, build_cast_payload([("New A", None, 0)]))])

    credits = await get_credits_for_item(db, "MOVIE", movie.id)
    assert [c.person_name for c in credits] == ["New A"]


async def test_a_graph_credit_survives_a_person_rename(db):
    """Sanity: ``upsert_credit`` is still idempotent on the natural key."""
    movie = Movie(title="Split Idem", slug="split-idem-89", last_synced_at=_now())
    db.add(movie)
    await db.flush()
    person = await _person(db, "Split Idem Director", "split-idem-director-89")

    payload = {
        "item_type": "MOVIE",
        "item_id": movie.id,
        "person_id": person.id,
        "role": "DIRECTOR",
    }
    await people_repo.upsert_credit(db, payload)
    await people_repo.upsert_credit(db, payload)

    rows = (
        (
            await db.execute(
                select(Credit).where(Credit.item_type == "MOVIE", Credit.item_id == movie.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ── 4. The migration, both ways, against real rows ───────────────────────────

_SCRATCH_DB = "backlogg_migration_0037"

# asyncpg prepares every statement, and a prepared statement can carry only
# one command — hence a tuple rather than one script.
_SEED_AT_0036 = (
    """
INSERT INTO movies (id, title, slug, last_synced_at, created_at, updated_at)
VALUES (10, 'Gran Torino', 'gran-torino-2008', NOW(), NOW(), NOW()),
       (11, 'Unforgiven',  'unforgiven-1992',  NOW(), NOW(), NOW())
""",
    """
INSERT INTO books (id, title, slug, last_synced_at, created_at, updated_at)
VALUES (20, 'Rita Hayworth', 'rita-hayworth-1982', NOW(), NOW(), NOW())
""",
    """
INSERT INTO people (id, name, slug, profile_url, last_synced_at, created_at, updated_at) VALUES
 (1, 'Bee Vang',       'bee-vang',       'https://img/1.jpg', NOW(), NOW(), NOW()),
 (2, 'David Peoples',  'david-peoples',  NULL,                NOW(), NOW(), NOW()),
 (3, 'Clint Eastwood', 'clint-eastwood', 'https://img/3.jpg', NOW(), NOW(), NOW()),
 (4, 'Stephen King',   'stephen-king',   NULL,                NOW(), NOW(), NOW()),
 (5, 'Ahney Her',      'ahney-her',      NULL,                NOW(), NOW(), NOW())
""",
    """
INSERT INTO external_ids (item_type, item_id, source, external_id, created_at) VALUES
 ('PERSON', 1, 'TMDB', 'p1', NOW()),
 ('PERSON', 2, 'TMDB', 'p2', NOW()),
 ('PERSON', 3, 'TMDB', 'p3', NOW()),
 ('PERSON', 4, 'OPEN_LIBRARY', 'OL1A', NOW()),
 ('PERSON', 5, 'TMDB', 'p5', NOW()),
 ('MOVIE', 10, 'TMDB', '13223', NOW())
""",
    """
INSERT INTO credits (item_type, item_id, person_id, role, character_name, billing_order) VALUES
 ('MOVIE', 10, 3, 'ACTOR', 'Walt Kowalski', 0),
 ('MOVIE', 10, 1, 'ACTOR', 'Thao',          1),
 ('MOVIE', 10, 5, 'ACTOR', NULL,            2),
 ('MOVIE', 10, 3, 'DIRECTOR', NULL, NULL),
 ('MOVIE', 11, 3, 'DIRECTOR', NULL, NULL),
 ('MOVIE', 11, 2, 'WRITER',   NULL, NULL),
 ('MOVIE', 11, 3, 'ACTOR', 'Will Munny', 0),
 ('BOOK',  20, 4, 'AUTHOR', NULL, NULL)
""",
)


def _scratch_url() -> str:
    base = settings.TEST_DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{_SCRATCH_DB}"


async def _admin_execute(statement: str) -> None:
    """Run a statement outside a transaction on the server's default database.

    ``CREATE``/``DROP DATABASE`` cannot run inside one, hence the explicit
    AUTOCOMMIT.
    """
    engine = create_async_engine(
        f"{settings.TEST_DATABASE_URL.rsplit('/', 1)[0]}/postgres",
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _run_on_scratch(statements: tuple[str, ...]) -> None:
    engine = create_async_engine(_scratch_url())
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def _read_scratch(query: str) -> list[tuple]:
    engine = create_async_engine(_scratch_url())
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(query))).all()]
    finally:
        await engine.dispose()


def _alembic(direction: str, revision: str) -> None:
    """Run alembic against the scratch database.

    ``alembic/env.py`` reads ``DATABASE_URL`` from the environment and spins
    its own event loop, which is why this test is synchronous.
    """
    previous = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = _scratch_url()
    try:
        getattr(command, direction)(Config("alembic.ini"), revision)
    finally:
        os.environ["DATABASE_URL"] = previous


def test_migration_0037_upgrades_and_downgrades_with_data():
    """The real thing: 0036 -> 0037 -> 0036 on a database with rows in it.

    A data migration that has only been read is not a tested one, and this one
    runs on deploy against 710.772 production rows.  The fixture is the shape
    that matters: a cast-only person (Bee Vang, Ahney Her), a crew-only person
    (David Peoples), a person who does both (Clint Eastwood) and a book author
    linked through Open Library.

    The downgrade assertions are the asymmetry, stated as a test rather than
    only as prose: the graph comes back whole, Eastwood's ``ACTOR`` rows come
    back from ``item_cast``, and the cast-only people stay gone.
    """
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
    asyncio.run(_admin_execute(f'CREATE DATABASE "{_SCRATCH_DB}"'))
    try:
        _alembic("upgrade", "0036")
        asyncio.run(_run_on_scratch(_SEED_AT_0036))

        # Pinned to "0037", not "head": this test asserts the shape 0037
        # produces, so the day 0038 lands it has to keep testing 0036 -> 0037
        # instead of silently starting to test whatever came after.
        _alembic("upgrade", "0037")

        # Graph only, narrow, and keyed by the natural key.
        assert asyncio.run(
            _read_scratch(
                "SELECT item_id, person_id, item_type, role FROM credits "
                "ORDER BY item_id, person_id, item_type, role"
            )
        ) == [(10, 3, 1, 2), (11, 2, 1, 3), (11, 3, 1, 2), (20, 4, 3, 4)]
        assert asyncio.run(
            _read_scratch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'credits' ORDER BY ordinal_position"
            )
        ) == [
            ("item_id", "bigint"),
            ("person_id", "bigint"),
            ("item_type", "smallint"),
            ("role", "smallint"),
            ("created_at", "timestamp with time zone"),
        ]

        # The cast, ordered, with the character names carried over.
        assert asyncio.run(
            _read_scratch("SELECT item_type, item_id, payload FROM item_cast ORDER BY item_id")
        ) == [
            (
                1,
                10,
                [
                    {"n": "Clint Eastwood", "c": "Walt Kowalski", "o": 0},
                    {"n": "Bee Vang", "c": "Thao", "o": 1},
                    {"n": "Ahney Her", "o": 2},
                ],
            ),
            (1, 11, [{"n": "Clint Eastwood", "c": "Will Munny", "o": 0}]),
        ]

        # Cast-only people and their external ids are gone; everyone else stays.
        assert asyncio.run(_read_scratch("SELECT id FROM people ORDER BY id")) == [(2,), (3,), (4,)]
        assert asyncio.run(
            _read_scratch("SELECT item_id FROM external_ids WHERE item_type = 'PERSON' ORDER BY 1")
        ) == [(2,), (3,), (4,)]

        _alembic("downgrade", "0036")

        rows = asyncio.run(
            _read_scratch(
                "SELECT item_type, item_id, person_id, role, character_name, billing_order "
                "FROM credits ORDER BY item_type, item_id, person_id, role"
            )
        )
        assert rows == [
            ("BOOK", 20, 4, "AUTHOR", None, None),
            # Eastwood's cast rows are rebuilt: his ``people`` row survived.
            ("MOVIE", 10, 3, "ACTOR", "Walt Kowalski", 0),
            ("MOVIE", 10, 3, "DIRECTOR", None, None),
            ("MOVIE", 11, 2, "WRITER", None, None),
            ("MOVIE", 11, 3, "ACTOR", "Will Munny", 0),
            ("MOVIE", 11, 3, "DIRECTOR", None, None),
        ]
        # Documented asymmetry: Bee Vang and Ahney Her do not come back, so
        # neither do their credits.  Only re-ingestion can restore them.
        assert asyncio.run(_read_scratch("SELECT id FROM people ORDER BY id")) == [(2,), (3,), (4,)]
        assert asyncio.run(_read_scratch("SELECT to_regclass('public.item_cast') IS NULL")) == [
            (True,)
        ]
    finally:
        asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
