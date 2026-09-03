"""Tests for feature 84 — the batch write path (``backlogg.shared.bulk_load``).

Everything here runs against the real PostgreSQL test database: the whole
point of the module is the COPY + ``INSERT ... SELECT ... ON CONFLICT``
mechanism, which cannot be exercised through a mock.

Covered (the acceptance list of feature 84):

- a batch of brand new rows lands complete (item, genres, external id,
  people and credits);
- re-running the same batch is idempotent;
- a mixed batch (new + already existing) updates and inserts in one go;
- an invalid row is dropped and *only* that row is lost;
- every person of a batch is resolved with a single query, and the number of
  SQL round trips does not grow with the number of credits;
- the batch route and the per-item route produce the same rows for the same
  input (every column of ``movies`` bar row identity, with non-null values);
- a lookup slug that fails to resolve is reported instead of silently
  costing the item its genre;
- a client-side column default is materialised when the payload omits it;
- the per-item fallback writes all four content types, not just movies.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, event, func, select, text

from backlogg.movies import repository as movies_repo
from backlogg.movies.models import Movie, MovieGenre, movie_genres_join
from backlogg.scheduler.jobs import _persist_people_individually, _write_items_individually
from backlogg.shared.bulk_load import (
    BulkItem,
    BulkPerson,
    bulk_load_items,
    copy_round_trips,
)
from backlogg.shared.external_ids import ExternalId
from backlogg.shared.models import Credit, Person

_SPEC = movies_repo.MOVIE_BULK_SPEC

_TX_CONTROL = {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}


def _movie_payload(slug: str, title: str, **overrides) -> dict:
    """A movie payload with the exact shape ``movie_to_dict`` produces."""
    data = {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A movie written by the batch loader.",
        "release_date": date(2020, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": 1000,
        "revenue": 2000,
        "status": "Released",
        "rating_external": 7.5,
        "rating_count_external": 42,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Bulk Drama", "slug": "bulk-drama"}],
    }
    data.update(overrides)
    return data


def _person(external_id: str, name: str, slug: str, **overrides) -> BulkPerson:
    fields = {
        "source": "TMDB",
        "external_id": external_id,
        "name": name,
        "slug": slug,
        "profile_url": None,
        "role": "ACTOR",
        "character_name": "Someone",
        "billing_order": 0,
    }
    fields.update(overrides)
    return BulkPerson(**fields)


class _StatementRecorder:
    """Counts the SQL statements SQLAlchemy issues inside the ``with`` block.

    COPY travels on the raw asyncpg connection, so it never reaches
    ``before_cursor_execute``; ``bulk_load`` counts it itself in
    ``copy_round_trips`` and both numbers are added up here.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []
        self._copy_baseline: dict[str, int] = {}

    def __enter__(self) -> "_StatementRecorder":
        self._copy_baseline = dict(copy_round_trips)
        event.listen(Engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info) -> None:
        event.remove(Engine, "before_cursor_execute", self._record)
        self.copies = copy_round_trips["copy"] - self._copy_baseline["copy"]

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        # Transaction control is the test fixture's business (the suite runs
        # inside a SAVEPOINT), not the loader's — it would make the count
        # depend on which test ran first.
        if statement.split(" ", 1)[0].upper() in _TX_CONTROL:
            return
        self.statements.append(statement)

    @property
    def round_trips(self) -> int:
        return len(self.statements) + self.copies

    def matching(self, needle: str) -> list[str]:
        return [s for s in self.statements if needle in s]


@contextmanager
def _captured_warnings():
    """Capture the loader's own warnings, robust to the rest of the suite.

    A handler on the module logger instead of ``caplog``: another test may
    have left logging globally disabled, which would silently empty the
    assertion (same reasoning as ``tests/users/test_account_recovery.py``).
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.NOTSET)
    module_logger = logging.getLogger("backlogg.shared.bulk_load")
    module_logger.addHandler(handler)
    previous_level = module_logger.level
    module_logger.setLevel(logging.WARNING)
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    previous_disabled_flag = module_logger.disabled
    module_logger.disabled = False
    try:
        yield records
    finally:
        module_logger.disabled = previous_disabled_flag
        logging.disable(previous_disable)
        module_logger.setLevel(previous_level)
        module_logger.removeHandler(handler)


async def _genre_slugs(db, movie_id: int) -> list[str]:
    result = await db.execute(
        select(MovieGenre.slug)
        .join(movie_genres_join, movie_genres_join.c.genre_id == MovieGenre.id)
        .where(movie_genres_join.c.movie_id == movie_id)
        .order_by(MovieGenre.slug)
    )
    return [row[0] for row in result.all()]


async def _credits_of(db, movie_id: int) -> list[tuple]:
    result = await db.execute(
        select(Person.slug, Credit.role, Credit.character_name, Credit.billing_order)
        .join(Person, Person.id == Credit.person_id)
        .where(Credit.item_type == "MOVIE", Credit.item_id == movie_id)
        .order_by(Person.slug, Credit.role)
    )
    return [tuple(row) for row in result.all()]


async def _movie(db, slug: str) -> Movie:
    result = await db.execute(select(Movie).where(Movie.slug == slug))
    return result.scalar_one()


# ── A batch of new rows ──────────────────────────────────────────────────────


async def test_batch_of_new_rows_writes_everything(db):
    """A batch of brand new items writes item, genres, external id and credits."""
    items = [
        BulkItem(
            data=_movie_payload("bulk-new-alpha", "Bulk New Alpha"),
            external_id="8400101",
            people=[_person("8400111", "Bulk Alpha Actor", "bulk-alpha-actor")],
        ),
        BulkItem(
            data=_movie_payload("bulk-new-beta", "Bulk New Beta"),
            external_id="8400102",
            people=[
                _person("8400111", "Bulk Alpha Actor", "bulk-alpha-actor"),
                _person(
                    "8400112",
                    "Bulk Beta Director",
                    "bulk-beta-director",
                    role="DIRECTOR",
                    character_name=None,
                    billing_order=None,
                ),
            ],
        ),
    ]

    outcome = await bulk_load_items(db, _SPEC, items)

    assert outcome.written == 2
    assert outcome.rejected == 0

    alpha = await _movie(db, "bulk-new-alpha")
    beta = await _movie(db, "bulk-new-beta")
    assert alpha.title == "Bulk New Alpha"
    assert alpha.runtime == 100
    assert alpha.release_date == date(2020, 1, 1)
    assert float(alpha.rating_external) == 7.5

    assert await _genre_slugs(db, alpha.id) == ["bulk-drama"]
    assert await _genre_slugs(db, beta.id) == ["bulk-drama"]

    external = await db.execute(
        select(ExternalId.external_id).where(
            ExternalId.item_type == "MOVIE", ExternalId.item_id == alpha.id
        )
    )
    assert external.scalar_one() == "8400101"

    assert await _credits_of(db, alpha.id) == [("bulk-alpha-actor", "ACTOR", "Someone", 0)]
    assert await _credits_of(db, beta.id) == [
        ("bulk-alpha-actor", "ACTOR", "Someone", 0),
        ("bulk-beta-director", "DIRECTOR", None, None),
    ]

    # The person shared by both items exists exactly once and is linked to the
    # external id that identifies them at TMDB.
    people_count = await db.execute(
        select(func.count()).select_from(Person).where(Person.slug == "bulk-alpha-actor")
    )
    assert people_count.scalar_one() == 1
    person_link = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == "PERSON",
            ExternalId.source == "TMDB",
            ExternalId.external_id == "8400111",
        )
    )
    assert person_link.scalar_one() is not None


# ── Idempotency ──────────────────────────────────────────────────────────────


async def test_batch_of_existing_rows_is_idempotent(db):
    """Re-running the very same batch updates in place — no duplicates anywhere."""

    def build() -> list[BulkItem]:
        return [
            BulkItem(
                data=_movie_payload("bulk-idem-alpha", "Bulk Idem Alpha"),
                external_id="8400201",
                people=[_person("8400211", "Bulk Idem Actor", "bulk-idem-actor")],
            )
        ]

    first = await bulk_load_items(db, _SPEC, build())
    second = await bulk_load_items(db, _SPEC, build())

    assert first.written == second.written == 1
    assert second.rejected == 0

    movies = await db.execute(
        select(func.count()).select_from(Movie).where(Movie.slug == "bulk-idem-alpha")
    )
    assert movies.scalar_one() == 1

    movie = await _movie(db, "bulk-idem-alpha")
    assert await _genre_slugs(db, movie.id) == ["bulk-drama"]
    assert await _credits_of(db, movie.id) == [("bulk-idem-actor", "ACTOR", "Someone", 0)]

    external = await db.execute(
        select(func.count())
        .select_from(ExternalId)
        .where(ExternalId.item_type == "MOVIE", ExternalId.item_id == movie.id)
    )
    assert external.scalar_one() == 1

    people = await db.execute(
        select(func.count()).select_from(Person).where(Person.slug == "bulk-idem-actor")
    )
    assert people.scalar_one() == 1


# ── Mixed batch ──────────────────────────────────────────────────────────────


async def test_mixed_batch_updates_existing_and_inserts_new(db):
    """One batch carrying an already-known item and a new one handles both."""
    await bulk_load_items(
        db,
        _SPEC,
        [
            BulkItem(
                data=_movie_payload("bulk-mixed-old", "Bulk Mixed Old"),
                external_id="8400301",
                people=[_person("8400311", "Bulk Mixed Actor", "bulk-mixed-actor")],
            )
        ],
    )

    outcome = await bulk_load_items(
        db,
        _SPEC,
        [
            BulkItem(
                data=_movie_payload(
                    "bulk-mixed-old",
                    "Bulk Mixed Old Retitled",
                    runtime=123,
                    genres=[{"name": "Bulk Comedy", "slug": "bulk-comedy"}],
                ),
                external_id="8400301",
                people=[
                    _person(
                        "8400311",
                        "Bulk Mixed Actor",
                        "bulk-mixed-actor",
                        character_name="Renamed",
                    )
                ],
            ),
            BulkItem(
                data=_movie_payload("bulk-mixed-new", "Bulk Mixed New"),
                external_id="8400302",
                people=[_person("8400312", "Bulk Fresh Actor", "bulk-fresh-actor")],
            ),
        ],
    )

    assert outcome.written == 2
    assert outcome.rejected == 0

    old = await _movie(db, "bulk-mixed-old")
    new = await _movie(db, "bulk-mixed-new")
    assert old.title == "Bulk Mixed Old Retitled"
    assert old.runtime == 123
    assert new.title == "Bulk Mixed New"

    # The source's genre list is authoritative: the old genre is replaced.
    assert await _genre_slugs(db, old.id) == ["bulk-comedy"]
    assert await _genre_slugs(db, new.id) == ["bulk-drama"]

    # The credit is updated in place, not duplicated.
    assert await _credits_of(db, old.id) == [("bulk-mixed-actor", "ACTOR", "Renamed", 0)]

    total = await db.execute(
        select(func.count())
        .select_from(Movie)
        .where(Movie.slug.in_(["bulk-mixed-old", "bulk-mixed-new"]))
    )
    assert total.scalar_one() == 2


# ── An invalid row is dropped, the batch is not ──────────────────────────────


async def test_invalid_row_is_dropped_and_the_rest_is_written(db):
    """A row that cannot legally reach the table costs only itself.

    ``title`` is NOT NULL, so this row would abort the whole COPY inside
    Postgres — the pre-validation catches it first (feature 84, decision D2).
    """
    items = [
        BulkItem(data=_movie_payload("bulk-bad-first", "Bulk Bad First"), external_id="8400401"),
        BulkItem(
            data=_movie_payload("bulk-bad-broken", None),
            external_id="8400402",
        ),
        BulkItem(data=_movie_payload("bulk-bad-last", "Bulk Bad Last"), external_id="8400403"),
    ]

    with _captured_warnings() as records:
        outcome = await bulk_load_items(db, _SPEC, items)

    assert outcome.written == 2
    assert outcome.rejected == 1
    # The drop is observable: a warning naming the row and the reason.
    assert any("bulk-bad-broken" in record.getMessage() for record in records)
    assert any("title" in record.getMessage() for record in records)

    surviving = await db.execute(
        select(Movie.slug).where(Movie.slug.like("bulk-bad-%")).order_by(Movie.slug)
    )
    assert [row[0] for row in surviving.all()] == ["bulk-bad-first", "bulk-bad-last"]


async def test_invalid_credit_is_dropped_without_costing_the_item(db):
    """A malformed credit is dropped on its own; the item and its good credits stay."""
    items = [
        BulkItem(
            data=_movie_payload("bulk-badcredit", "Bulk Bad Credit"),
            external_id="8400501",
            people=[
                _person("8400511", "Bulk Good Actor", "bulk-good-actor"),
                # No external id: the person cannot be identified at the source.
                _person("", "Bulk Nameless", "bulk-nameless"),
            ],
        )
    ]

    outcome = await bulk_load_items(db, _SPEC, items)

    assert outcome.written == 1
    assert outcome.people_rejected == 1
    movie = await _movie(db, "bulk-badcredit")
    assert await _credits_of(db, movie.id) == [("bulk-good-actor", "ACTOR", "Someone", 0)]


# ── People are resolved once per batch, not twice per person ─────────────────


def _people_lookup_statements(recorder: _StatementRecorder) -> list[str]:
    """The person-resolution SELECT — the only one that reads external_ids.item_id."""
    return [
        statement
        for statement in recorder.statements
        if "external_ids.item_id" in statement and statement.lstrip().upper().startswith("SELECT")
    ]


async def test_people_of_a_batch_are_resolved_with_a_single_query(db):
    """Acceptance #2: one SELECT resolves every person of the batch."""
    people = [
        _person(f"84006{index:02d}", f"Bulk Crowd {index}", f"bulk-crowd-{index}")
        for index in range(6)
    ]
    items = [
        BulkItem(
            data=_movie_payload("bulk-crowd-alpha", "Bulk Crowd Alpha"),
            external_id="8400601",
            people=people[:3],
        ),
        BulkItem(
            data=_movie_payload("bulk-crowd-beta", "Bulk Crowd Beta"),
            external_id="8400602",
            people=people[3:],
        ),
    ]

    with _StatementRecorder() as recorder:
        outcome = await bulk_load_items(db, _SPEC, items)

    assert outcome.written == 2
    assert len(_people_lookup_statements(recorder)) == 1

    movie = await _movie(db, "bulk-crowd-alpha")
    assert len(await _credits_of(db, movie.id)) == 3


async def test_round_trips_do_not_grow_with_the_number_of_credits(db):
    """The batch cost is per batch, not per person — the whole point of feature 84."""

    def batch(prefix: str, base: int, credits: int) -> list[BulkItem]:
        return [
            BulkItem(
                data=_movie_payload(f"bulk-{prefix}", f"Bulk {prefix}"),
                external_id=str(base),
                people=[
                    _person(
                        str(base + 1 + index),
                        f"Bulk {prefix} Person {index}",
                        f"bulk-{prefix}-person-{index}",
                    )
                    for index in range(credits)
                ],
            )
        ]

    with _StatementRecorder() as few:
        await bulk_load_items(db, _SPEC, batch("few", 8400700, credits=2))
    with _StatementRecorder() as many:
        await bulk_load_items(db, _SPEC, batch("many", 8400800, credits=12))

    assert few.round_trips == many.round_trips


async def test_round_trips_do_not_grow_with_the_number_of_items(db):
    """The same fixed cost writes one item or twenty — round trips are per batch.

    This is the causal proof behind the benchmark: it holds regardless of the
    latency of the database the batch runs against.
    """

    def batch(prefix: str, base: int, size: int) -> list[BulkItem]:
        return [
            BulkItem(
                data=_movie_payload(f"bulk-{prefix}-{index}", f"Bulk {prefix} {index}"),
                external_id=str(base + index),
                people=[
                    _person(
                        str(base + 500 + index),
                        f"Bulk {prefix} Person {index}",
                        f"bulk-{prefix}-person-{index}",
                    )
                ],
            )
            for index in range(size)
        ]

    with _StatementRecorder() as one:
        outcome_one = await bulk_load_items(db, _SPEC, batch("one", 8401000, size=1))
    with _StatementRecorder() as twenty:
        outcome_twenty = await bulk_load_items(db, _SPEC, batch("twenty", 8402000, size=20))

    assert outcome_one.written == 1
    assert outcome_twenty.written == 20
    assert one.round_trips == twenty.round_trips
    # 20 items for the price of one batch: well under the 35-75 round trips a
    # single item cost on the per-item route.
    assert twenty.round_trips / 20 < 2


# ── Batch route vs per-item route ────────────────────────────────────────────


# Columns deliberately left out of the equivalence snapshot: they are row
# identity or wall-clock bookkeeping filled by Postgres, so two rows written
# at two different moments can never match on them.
_SNAPSHOT_EXEMPT = {"id", "created_at", "updated_at"}


async def _snapshot(db, slug: str) -> dict:
    """Everything about a persisted movie that both routes must agree on.

    Every column of ``movies`` except ``_SNAPSHOT_EXEMPT`` is in here — the
    coverage is asserted, not assumed, so a column added later cannot quietly
    escape the comparison.
    """
    movie = await _movie(db, slug)
    external = await db.execute(
        select(ExternalId.source, ExternalId.external_id).where(
            ExternalId.item_type == "MOVIE", ExternalId.item_id == movie.id
        )
    )
    snapshot = {
        "slug": movie.slug,
        "title": movie.title,
        "original_title": movie.original_title,
        "overview": movie.overview,
        "release_date": movie.release_date,
        "runtime": movie.runtime,
        "original_language": movie.original_language,
        "poster_url": movie.poster_url,
        "backdrop_url": movie.backdrop_url,
        "budget": movie.budget,
        "revenue": movie.revenue,
        "status": movie.status,
        "rating_external": movie.rating_external,
        "rating_count_external": movie.rating_count_external,
        "rating_internal": movie.rating_internal,
        "rating_count_internal": movie.rating_count_internal,
        "locked_fields": list(movie.locked_fields),
        "last_synced_at": movie.last_synced_at,
        "genres": await _genre_slugs(db, movie.id),
        "external_ids": sorted(tuple(row) for row in external.all()),
        "credits": await _credits_of(db, movie.id),
    }
    covered = {name for name in Movie.__table__.columns.keys() if name not in _SNAPSHOT_EXEMPT}
    assert covered <= set(snapshot), (
        f"columns missing from the equivalence snapshot: {sorted(covered - set(snapshot))}"
    )
    return snapshot


async def _wipe(db, slug: str) -> None:
    """Remove a movie and everything the routes attached to it."""
    movie = await _movie(db, slug)
    await db.execute(
        text("DELETE FROM credits WHERE item_type = 'MOVIE' AND item_id = :id"), {"id": movie.id}
    )
    await db.execute(
        text("DELETE FROM external_ids WHERE item_type = 'MOVIE' AND item_id = :id"),
        {"id": movie.id},
    )
    await db.execute(text("DELETE FROM movie_genres_join WHERE movie_id = :id"), {"id": movie.id})
    await db.execute(text("DELETE FROM movies WHERE id = :id"), {"id": movie.id})
    db.expunge_all()


async def test_batch_route_matches_per_item_route(db):
    """Acceptance #3/#5: both routes leave the database in the same state.

    The same payload is written twice — once through the batch loader, once
    through the untouched per-item repositories — with the rows removed in
    between, and the two snapshots are compared field by field.

    Every nullable column carries a *non-null* value here on purpose: a field
    that is ``None`` on both sides proves nothing, so ``poster_url``,
    ``backdrop_url`` and ``rating_internal`` are filled in rather than left at
    the defaults of ``_movie_payload``.
    """
    slug = "bulk-equivalence"
    people = [
        _person("8400911", "Bulk Equi Actor", "bulk-equi-actor"),
        _person(
            "8400912",
            "Bulk Equi Director",
            "bulk-equi-director",
            role="DIRECTOR",
            character_name=None,
            billing_order=None,
        ),
    ]

    synced_at = datetime(2024, 5, 4, 3, 2, 1, tzinfo=UTC)

    def payload() -> dict:
        return _movie_payload(
            slug,
            "Bulk Equivalence",
            poster_url="https://image.example/poster-equivalence.jpg",
            backdrop_url="https://image.example/backdrop-equivalence.jpg",
            rating_internal=Decimal("6.25"),
            rating_count_internal=0,
            last_synced_at=synced_at,
            genres=[
                {"name": "Bulk Drama", "slug": "bulk-drama"},
                {"name": "Bulk Comedy", "slug": "bulk-comedy"},
            ],
        )

    await bulk_load_items(
        db,
        _SPEC,
        [BulkItem(data=payload(), external_id="8400901", people=list(people))],
    )
    batch_state = await _snapshot(db, slug)
    await _wipe(db, slug)

    # Per-item route, exactly as the on-demand path and the fallback use it.
    movie = await movies_repo.upsert_movie(db, payload())
    from backlogg.shared.external_ids import upsert_external_id

    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "8400901")
    await _persist_people_individually(db, "MOVIE", movie.id, list(people))
    await db.flush()
    db.expunge_all()
    per_item_state = await _snapshot(db, slug)

    assert batch_state == per_item_state


# ── The other content types ──────────────────────────────────────────────────


async def test_game_batch_writes_genres_platforms_and_company_credits(db):
    """The game spec is the widest one: two lookups plus non-person credits."""
    from backlogg.games import repository as games_repo
    from backlogg.games.models import Company, CompanyCredit, Game

    payload = {
        "title": "Bulk Bench Game",
        "original_title": None,
        "slug": "bulk-bench-game",
        "overview": "A game written by the batch loader.",
        "release_date": date(2021, 3, 3),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 8.1,
        "rating_count_external": 300,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Bulk Shooter", "slug": "bulk-shooter"}],
        "platforms": [{"name": "Bulk Console", "slug": "bulk-console"}],
        "companies": [
            {"name": "Bulk Studio", "slug": "bulk-studio", "role": "DEVELOPER"},
            {"name": "Bulk Studio", "slug": "bulk-studio", "role": "PUBLISHER"},
        ],
    }

    outcome = await bulk_load_items(
        db,
        games_repo.GAME_BULK_SPEC,
        [BulkItem(data=payload, external_id="8401101")],
    )
    assert outcome.written == 1

    game = (await db.execute(select(Game).where(Game.slug == "bulk-bench-game"))).scalar_one()
    assert game.game_type == "MAIN_GAME"

    roles = await db.execute(
        select(CompanyCredit.role)
        .join(Company, Company.id == CompanyCredit.company_id)
        .where(
            CompanyCredit.item_type == "GAME",
            CompanyCredit.item_id == game.id,
            Company.slug == "bulk-studio",
        )
        .order_by(CompanyCredit.role)
    )
    assert [row[0] for row in roles.all()] == ["DEVELOPER", "PUBLISHER"]

    genres = await db.execute(
        text(
            "SELECT g.slug FROM game_genres g JOIN game_genres_join j ON j.genre_id = g.id "
            "WHERE j.game_id = :id"
        ),
        {"id": game.id},
    )
    assert [row[0] for row in genres.all()] == ["bulk-shooter"]
    platforms = await db.execute(
        text(
            "SELECT p.slug FROM game_platforms p JOIN game_platforms_join j "
            "ON j.platform_id = p.id WHERE j.game_id = :id"
        ),
        {"id": game.id},
    )
    assert [row[0] for row in platforms.all()] == ["bulk-console"]


async def test_series_and_book_batches_write_their_own_tables(db):
    """The remaining two specs write through the same generic loader."""
    from backlogg.books import repository as books_repo
    from backlogg.books.models import Book
    from backlogg.series import repository as series_repo
    from backlogg.series.models import Series

    series_payload = {
        "title": "Bulk Bench Series",
        "original_title": "Bulk Bench Series",
        "slug": "bulk-bench-series",
        "overview": "A series written by the batch loader.",
        "first_air_date": date(2019, 9, 1),
        "last_air_date": date(2023, 6, 1),
        "number_of_seasons": 3,
        "number_of_episodes": 30,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 8.5,
        "rating_count_external": 500,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Bulk Sci-Fi", "slug": "bulk-sci-fi"}],
    }
    book_payload = {
        "title": "Bulk Bench Book",
        "original_title": None,
        "slug": "bulk-bench-book",
        "overview": "A book written by the batch loader.",
        "first_publish_date": date(2005, 4, 4),
        "original_language": None,
        "poster_url": None,
        "isbn": "9780000000001",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Bulk Fiction", "slug": "bulk-fiction"}],
    }

    series_outcome = await bulk_load_items(
        db,
        series_repo.SERIES_BULK_SPEC,
        [
            BulkItem(
                data=series_payload,
                external_id="8401201",
                people=[
                    _person(
                        "8401211",
                        "Bulk Series Creator",
                        "bulk-series-creator",
                        role="CREATOR",
                        character_name=None,
                        billing_order=None,
                    )
                ],
            )
        ],
    )
    book_outcome = await bulk_load_items(
        db,
        books_repo.BOOK_BULK_SPEC,
        [
            BulkItem(
                data=book_payload,
                external_id="OL8401301W",
                people=[
                    _person(
                        "OL8401311A",
                        "Bulk Book Author",
                        "bulk-book-author",
                        source="OPEN_LIBRARY",
                        role="AUTHOR",
                        character_name=None,
                        billing_order=None,
                    )
                ],
            )
        ],
    )

    assert series_outcome.written == 1
    assert book_outcome.written == 1

    series = (
        await db.execute(select(Series).where(Series.slug == "bulk-bench-series"))
    ).scalar_one()
    book = (await db.execute(select(Book).where(Book.slug == "bulk-bench-book"))).scalar_one()
    assert series.number_of_seasons == 3
    assert book.isbn == "9780000000001"

    series_credits = await db.execute(
        select(Credit.role).where(Credit.item_type == "SERIES", Credit.item_id == series.id)
    )
    assert [row[0] for row in series_credits.all()] == ["CREATOR"]
    book_credits = await db.execute(
        select(Credit.role).where(Credit.item_type == "BOOK", Credit.item_id == book.id)
    )
    assert [row[0] for row in book_credits.all()] == ["AUTHOR"]


# ── A genre that cannot be resolved is never dropped in silence ──────────────


async def test_unresolvable_lookup_slug_is_reported(db, monkeypatch):
    """The one path where the batch route could quietly write less than asked.

    ``_load_lookup_rows`` now upserts with ``DO UPDATE ... RETURNING``, which
    waits for a concurrent writer and always yields a row, so a slug going
    missing should be impossible.  If it ever happens anyway, the item must
    not lose the genre without a trace: forcing an empty mapping proves the
    warning names the item type, the lookup table and the slug.
    """
    import backlogg.shared.bulk_load as bulk_load_module

    async def _no_ids(*args, **kwargs):
        return {}

    monkeypatch.setattr(bulk_load_module, "_load_lookup_rows", _no_ids)

    with _captured_warnings() as records:
        outcome = await bulk_load_items(
            db,
            _SPEC,
            [
                BulkItem(
                    data=_movie_payload("bulk-lost-genre", "Bulk Lost Genre"),
                    external_id="8401601",
                )
            ],
        )

    assert outcome.written == 1
    movie = await _movie(db, "bulk-lost-genre")
    assert await _genre_slugs(db, movie.id) == []
    messages = [record.getMessage() for record in records]
    assert any(
        "MOVIE" in message and "movie_genres" in message and "bulk-drama" in message
        for message in messages
    ), messages


# ── Client-side column defaults (the COPY does not fire them by itself) ──────


async def test_client_side_default_is_materialised_when_the_payload_omits_it(db):
    """A payload without ``rating_count_internal`` must not violate its NOT NULL.

    ``rating_count_internal`` is ``nullable=False`` with a *client-side*
    ``default=0``: SQLAlchemy applies it when the ORM builds the INSERT, but
    the batch route writes with raw SQL after a COPY, so nothing would fire it
    and the whole batch would die on the NOT NULL.  ``_python_default`` /
    ``_defaulted_columns`` exist for exactly this, and every other payload in
    the suite (like every ``*_to_dict``) happens to emit the key, so this is
    the only test that walks that branch.
    """
    payload = _movie_payload("bulk-default-count", "Bulk Default Count")
    del payload["rating_count_internal"]

    outcome = await bulk_load_items(db, _SPEC, [BulkItem(data=payload, external_id="8401401")])

    assert outcome.written == 1
    assert outcome.rejected == 0
    stored = await db.execute(
        select(Movie.rating_count_internal).where(Movie.slug == "bulk-default-count")
    )
    assert stored.scalar_one() == 0

    # And on the *update* half of the upsert the default must not clobber a
    # count the community already earned: it is one of the never-updated
    # columns, exactly like the per-item route.
    await db.execute(
        text("UPDATE movies SET rating_count_internal = 5 WHERE slug = :slug"),
        {"slug": "bulk-default-count"},
    )
    again = _movie_payload("bulk-default-count", "Bulk Default Count Again")
    del again["rating_count_internal"]
    await bulk_load_items(db, _SPEC, [BulkItem(data=again, external_id="8401401")])

    row = await db.execute(
        select(Movie.title, Movie.rating_count_internal).where(Movie.slug == "bulk-default-count")
    )
    assert tuple(row.one()) == ("Bulk Default Count Again", 5)


# ── The per-item fallback, for all four content types ────────────────────────


def _fallback_case(item_type: str) -> dict:
    """Spec + payload + expectations for one content type's per-item fallback."""
    from backlogg.books import repository as books_repo
    from backlogg.games import repository as games_repo
    from backlogg.series import repository as series_repo

    now = datetime.now(UTC)
    if item_type == "MOVIE":
        return {
            "spec": movies_repo.MOVIE_BULK_SPEC,
            "external_id": "8401501",
            "payload": _movie_payload("bulk-fallback-movie", "Bulk Fallback Movie"),
            "people": [_person("8401511", "Bulk Fallback Actor", "bulk-fallback-actor")],
            "table": "movies",
            "genre_sql": (
                "SELECT g.slug FROM movie_genres g JOIN movie_genres_join j "
                "ON j.genre_id = g.id WHERE j.movie_id = :id"
            ),
            "genres": ["bulk-drama"],
            "roles": ["ACTOR"],
        }
    if item_type == "SERIES":
        return {
            "spec": series_repo.SERIES_BULK_SPEC,
            "external_id": "8401502",
            "payload": {
                "title": "Bulk Fallback Series",
                "original_title": "Bulk Fallback Series",
                "slug": "bulk-fallback-series",
                "overview": "A series written by the per-item fallback.",
                "first_air_date": date(2019, 9, 1),
                "last_air_date": date(2023, 6, 1),
                "number_of_seasons": 3,
                "number_of_episodes": 30,
                "status": "Ended",
                "original_language": "en",
                "poster_url": None,
                "backdrop_url": None,
                "rating_external": 8.5,
                "rating_count_external": 500,
                "rating_internal": None,
                "rating_count_internal": 0,
                "last_synced_at": now,
                "genres": [{"name": "Bulk Sci-Fi", "slug": "bulk-sci-fi"}],
            },
            "people": [
                _person(
                    "8401512",
                    "Bulk Fallback Creator",
                    "bulk-fallback-creator",
                    role="CREATOR",
                    character_name=None,
                    billing_order=None,
                )
            ],
            "table": "series",
            "genre_sql": (
                "SELECT g.slug FROM series_genres g JOIN series_genres_join j "
                "ON j.genre_id = g.id WHERE j.series_id = :id"
            ),
            "genres": ["bulk-sci-fi"],
            "roles": ["CREATOR"],
        }
    if item_type == "BOOK":
        return {
            "spec": books_repo.BOOK_BULK_SPEC,
            "external_id": "OL8401503W",
            "payload": {
                "title": "Bulk Fallback Book",
                "original_title": None,
                "slug": "bulk-fallback-book",
                "overview": "A book written by the per-item fallback.",
                "first_publish_date": date(2005, 4, 4),
                "original_language": None,
                "poster_url": None,
                "isbn": "9780000000002",
                "rating_external": None,
                "rating_count_external": None,
                "rating_internal": None,
                "rating_count_internal": 0,
                "last_synced_at": now,
                "genres": [{"name": "Bulk Fiction", "slug": "bulk-fiction"}],
            },
            "people": [
                _person(
                    "OL8401513A",
                    "Bulk Fallback Author",
                    "bulk-fallback-author",
                    source="OPEN_LIBRARY",
                    role="AUTHOR",
                    character_name=None,
                    billing_order=None,
                )
            ],
            "table": "books",
            "genre_sql": (
                "SELECT g.slug FROM book_genres g JOIN book_genres_join j "
                "ON j.genre_id = g.id WHERE j.book_id = :id"
            ),
            "genres": ["bulk-fiction"],
            "roles": ["AUTHOR"],
        }
    return {
        "spec": games_repo.GAME_BULK_SPEC,
        "external_id": "8401504",
        "payload": {
            "title": "Bulk Fallback Game",
            "original_title": None,
            "slug": "bulk-fallback-game",
            "overview": "A game written by the per-item fallback.",
            "release_date": date(2021, 3, 3),
            "game_type": "MAIN_GAME",
            "original_language": None,
            "poster_url": None,
            "backdrop_url": None,
            "rating_external": 8.1,
            "rating_count_external": 300,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": now,
            "genres": [{"name": "Bulk Shooter", "slug": "bulk-shooter"}],
            "platforms": [{"name": "Bulk Console", "slug": "bulk-console"}],
            "companies": [{"name": "Bulk Studio", "slug": "bulk-studio", "role": "DEVELOPER"}],
        },
        # Games have no people: their credits are company credits, written by
        # ``upsert_game`` itself.
        "people": [],
        "table": "games",
        "genre_sql": (
            "SELECT g.slug FROM game_genres g JOIN game_genres_join j "
            "ON j.genre_id = g.id WHERE j.game_id = :id"
        ),
        "genres": ["bulk-shooter"],
        "roles": [],
    }


@pytest.mark.parametrize("item_type", ["MOVIE", "SERIES", "BOOK", "GAME"])
async def test_per_item_fallback_writes_every_content_type(db, item_type):
    """The D2 safety net has to work for all four types, not just movies.

    ``_write_items_individually`` is what runs when a batch fails, so each
    spec's ``_bulk_fallback_upsert`` is on the critical path of "the batch
    route is never worse than the old one".  It writes the item, its genres,
    its external id and its credits — one commit per item.
    """
    case = _fallback_case(item_type)
    items = [
        BulkItem(
            data=case["payload"],
            external_id=case["external_id"],
            people=list(case["people"]),
        )
    ]

    synced, errors, people_errors = await _write_items_individually(
        db, case["spec"], items, "test_fallback"
    )

    assert (synced, errors, people_errors) == (1, 0, 0)
    # The batch payload must survive the fallback untouched: the per-item
    # upserts pop the relation keys off the dict they are handed.
    assert "genres" in items[0].data

    slug = case["payload"]["slug"]
    row = await db.execute(
        text(f'SELECT "id", "title" FROM "{case["table"]}" WHERE "slug" = :slug'), {"slug": slug}
    )
    item_id, title = row.one()
    assert title == case["payload"]["title"]

    genres = await db.execute(text(case["genre_sql"]), {"id": item_id})
    assert sorted(r[0] for r in genres.all()) == case["genres"]

    external = await db.execute(
        select(ExternalId.source, ExternalId.external_id).where(
            ExternalId.item_type == case["spec"].item_type, ExternalId.item_id == item_id
        )
    )
    assert [tuple(r) for r in external.all()] == [
        (case["spec"].source, case["external_id"]),
    ]

    credits = await db.execute(
        select(Credit.role)
        .where(Credit.item_type == case["spec"].item_type, Credit.item_id == item_id)
        .order_by(Credit.role)
    )
    assert [r[0] for r in credits.all()] == case["roles"]

    if item_type == "GAME":
        from backlogg.games.models import Company, CompanyCredit

        companies = await db.execute(
            select(Company.slug, CompanyCredit.role)
            .join(Company, Company.id == CompanyCredit.company_id)
            .where(CompanyCredit.item_type == "GAME", CompanyCredit.item_id == item_id)
        )
        assert [tuple(r) for r in companies.all()] == [("bulk-studio", "DEVELOPER")]


# ── Slice size resolution (acceptance #7) ────────────────────────────────────


@pytest.mark.parametrize(
    ("item_type", "setting_name"),
    [
        ("MOVIE", "SYNC_SLICE_SIZE_MOVIES"),
        ("SERIES", "SYNC_SLICE_SIZE_SERIES"),
        ("BOOK", "SYNC_SLICE_SIZE_BOOKS"),
        ("GAME", "SYNC_SLICE_SIZE_GAMES"),
    ],
)
def test_slice_size_prefers_the_per_type_setting(monkeypatch, item_type, setting_name):
    """Each type reads its own slice size, falling back to the global one."""
    from backlogg.scheduler import jobs as sync_jobs

    monkeypatch.setattr(sync_jobs.settings, "SYNC_SLICE_SIZE", 200)
    monkeypatch.setattr(sync_jobs.settings, setting_name, None)
    assert sync_jobs._resolve_slice_size(item_type, None) == 200

    monkeypatch.setattr(sync_jobs.settings, setting_name, 350)
    assert sync_jobs._resolve_slice_size(item_type, None) == 350

    # An explicit argument (the backfill script's --slice-size) wins over both.
    assert sync_jobs._resolve_slice_size(item_type, 900) == 900


def test_per_type_slice_sizes_default_to_none():
    """The defaults must not change production behaviour on deploy."""
    from backlogg.core.config import Settings

    defaults = Settings.model_fields
    for name in (
        "SYNC_SLICE_SIZE_MOVIES",
        "SYNC_SLICE_SIZE_SERIES",
        "SYNC_SLICE_SIZE_BOOKS",
        "SYNC_SLICE_SIZE_GAMES",
    ):
        assert defaults[name].default is None
    assert defaults["SYNC_SLICE_SIZE"].default == 200
