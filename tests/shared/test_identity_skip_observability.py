"""Issue #24 — the external id a row could not keep, counted as its own class.

``skipped_links`` (issue #22) instruments one of the two unique keys of
``external_ids``: ``uq_external_id``, two items fighting over one external id.
The mirror image is ``uq_item_source`` — **one row holding two external ids of
the same source**, which the constraint does not allow either.

It happens when two identities of the source collapse onto a single catalog
row: two people whose names slugify identically resolve to the same
``people.id`` through ``_resolve_people``'s
``ON CONFLICT ON CONSTRAINT uq_people_slug``, and from there only one of the
two TMDB ids fits.  The loser is dropped, the item still *looks* linked, and
``skipped_links`` structurally cannot see it: there the ``item_id`` is the
same, which is precisely its idempotency discriminant.

The product decision of 2026-09-12 keeps the behaviour — two homonyms stay one
row — so what is under test here is that the catalog now **says so**:

1. the drop is counted in ``LinkSkipCollector.identity_count`` and logged with
   both ids, on the per-item path *and* on the batch path (inside one batch and
   against a row already in the database);
2. idempotency stays silent, exactly like the link counter: re-offering the id
   a row already holds is not a loss;
3. the two counters never blur into each other — a skipped link is not a
   skipped identity and vice versa;
4. outside a collector it is a no-op, so the on-demand paths pay nothing;
5. the batch path did not buy it with an extra round trip — the pre-check reads
   one more ``OR`` branch, not one more query;
6. the number reaches the end of the road it shares with ``skipped_links``:
   job result dict -> ``POST /admin/sync/{type}``.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime

from sqlalchemy import select

from backlogg.admin.schemas import SyncResponse
from backlogg.movies import repository as movies_repo
from backlogg.movies.models import Movie
from backlogg.shared.bulk_load import (
    BulkItem,
    BulkPerson,
    _Staging,
    _upsert_external_ids,
    bulk_load_items,
)
from backlogg.shared.external_ids import (
    MAX_TRACKED_LINK_SKIPS,
    ExternalId,
    collect_link_skips,
    record_identity_skip,
    upsert_external_id,
)
from backlogg.shared.models import Person
from tests.shared.test_bulk_load import _StatementRecorder

_SPEC = movies_repo.MOVIE_BULK_SPEC


def _now() -> datetime:
    return datetime.now(UTC)


def _movie_payload(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "release_date": date(2019, 5, 4),
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


async def _movie(db, slug: str, title: str = "Identity Movie") -> Movie:
    movie = Movie(title=title, slug=slug, release_date=date(2019, 5, 4), last_synced_at=_now())
    db.add(movie)
    await db.flush()
    return movie


async def _linked_id(db, item_type: str, item_id: int, source: str) -> str | None:
    result = await db.execute(
        select(ExternalId.external_id).where(
            ExternalId.item_type == item_type,
            ExternalId.item_id == item_id,
            ExternalId.source == source,
        )
    )
    return result.scalar_one_or_none()


@contextmanager
def _captured_warnings():
    """Capture ``external_ids``' own warnings, robust to the rest of the suite.

    A handler on the module logger instead of ``caplog``: another test may have
    left logging globally disabled, which would silently empty the assertion.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.NOTSET)
    module_logger = logging.getLogger("backlogg.shared.external_ids")
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


# ── Per-item path (``upsert_external_id``) ───────────────────────────────────


async def test_a_second_external_id_on_the_same_row_is_counted(db):
    """The shape issue #24 describes: one row, two source identities.

    The newcomer still wins — behaviour is deliberately unchanged, ``ON
    CONFLICT ON CONSTRAINT uq_item_source DO UPDATE`` is what it always was —
    but the id it displaced is now named.
    """
    movie = await _movie(db, "identity-skip-per-item")

    with collect_link_skips() as skips:
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300001")
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300002")

    assert skips.identity_count == 1
    skip = skips.identity_skips[0]
    assert (skip.item_type, skip.source, skip.item_id) == ("MOVIE", "TMDB", movie.id)
    assert (skip.kept_external_id, skip.dropped_external_id) == ("9300002", "9300001")
    # Unchanged behaviour: the row keeps the last id offered.
    assert await _linked_id(db, "MOVIE", movie.id, "TMDB") == "9300002"
    # And it is *not* a skipped link: no other item wanted either id.
    assert skips.count == 0


async def test_re_offering_the_same_id_is_not_an_identity_skip(db):
    """Idempotency stays silent, same rule as the link counter."""
    movie = await _movie(db, "identity-skip-idempotent")

    with collect_link_skips() as skips:
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300003")
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300003")

    assert skips.identity_count == 0
    assert skips.identity_skips == []


async def test_two_ids_of_different_sources_coexist_without_a_skip(db):
    """``uq_item_source`` is per source: TMDB and IGDB on one row is not a loss."""
    movie = await _movie(db, "identity-skip-two-sources")

    with collect_link_skips() as skips:
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300004")
        await upsert_external_id(db, "MOVIE", movie.id, "IGDB", "9300004")

    assert skips.identity_count == 0
    assert await _linked_id(db, "MOVIE", movie.id, "IGDB") == "9300004"
    assert await _linked_id(db, "MOVIE", movie.id, "TMDB") == "9300004"


async def test_a_dropped_identity_is_logged_with_both_ids(db):
    """A log line even outside a collector — whoever triggered it deserves one."""
    movie = await _movie(db, "identity-skip-logged")

    with _captured_warnings() as records:
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300005")
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300006")

    messages = [record.getMessage() for record in records]
    dropped = [m for m in messages if "identity skipped" in m]
    assert len(dropped) == 1
    assert "9300005" in dropped[0] and "9300006" in dropped[0]
    assert str(movie.id) in dropped[0]


async def test_outside_a_collector_the_identity_skip_is_a_no_op(db):
    """On-demand paths must neither pay for it nor fail on it."""
    movie = await _movie(db, "identity-skip-no-collector")

    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300007")
    row = await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9300008")

    assert row.external_id == "9300008"


def test_record_identity_skip_without_a_collector_is_a_no_op():
    record_identity_skip("PERSON", "TMDB", 1, "2", "3")  # must not raise


def test_the_identity_detail_list_is_capped_but_the_count_is_not():
    """Same memory guarantee as the link collector: exact count, bounded detail."""
    with collect_link_skips() as skips:
        for i in range(MAX_TRACKED_LINK_SKIPS + 25):
            record_identity_skip("PERSON", "TMDB", 1, str(i), str(i + 1))

    assert skips.identity_count == MAX_TRACKED_LINK_SKIPS + 25
    assert len(skips.identity_skips) == MAX_TRACKED_LINK_SKIPS


# ── Batch path (``_upsert_external_ids``) ────────────────────────────────────


async def test_two_ids_for_one_item_inside_a_batch_are_counted(db):
    """The ``by_item`` de-duplication: last wins, and the loser is now named.

    This is the branch issue #24 is about — before it, the dropped row had the
    same ``item_id`` as the winner, so ``record_link_skip``'s discriminant read
    it as idempotency and said nothing.
    """
    movie = await _movie(db, "identity-skip-batch-inside")

    with collect_link_skips() as skips:
        await _upsert_external_ids(
            db,
            _Staging(db),
            [
                ("MOVIE", movie.id, "TMDB", "9300010"),
                ("MOVIE", movie.id, "TMDB", "9300011"),
            ],
        )

    assert skips.identity_count == 1
    skip = skips.identity_skips[0]
    assert (skip.kept_external_id, skip.dropped_external_id) == ("9300011", "9300010")
    assert skips.count == 0
    assert await _linked_id(db, "MOVIE", movie.id, "TMDB") == "9300011"


async def test_the_same_id_twice_in_a_batch_is_not_an_identity_skip(db):
    """Exact duplicates inside one batch are de-duplication, not loss."""
    movie = await _movie(db, "identity-skip-batch-dup")

    with collect_link_skips() as skips:
        await _upsert_external_ids(
            db,
            _Staging(db),
            [
                ("MOVIE", movie.id, "TMDB", "9300012"),
                ("MOVIE", movie.id, "TMDB", "9300012"),
            ],
        )

    assert skips.identity_count == 0


async def test_a_batch_displacing_a_stored_id_is_counted(db):
    """The other half: the row already holds an id *in the database*.

    The ``ON CONFLICT ON CONSTRAINT uq_item_source DO UPDATE`` overwrites it
    without a word; the pre-check now reads that row in the same query.
    """
    movie = await _movie(db, "identity-skip-batch-stored")
    await _upsert_external_ids(db, _Staging(db), [("MOVIE", movie.id, "TMDB", "9300013")])

    with collect_link_skips() as skips:
        await _upsert_external_ids(db, _Staging(db), [("MOVIE", movie.id, "TMDB", "9300014")])

    assert skips.identity_count == 1
    skip = skips.identity_skips[0]
    assert (skip.kept_external_id, skip.dropped_external_id) == ("9300014", "9300013")
    assert await _linked_id(db, "MOVIE", movie.id, "TMDB") == "9300014"


async def test_rerunning_the_same_batch_counts_no_identity_skip(db):
    """The nightly job re-offers the very same links every night."""
    movie = await _movie(db, "identity-skip-batch-rerun")

    await _upsert_external_ids(db, _Staging(db), [("MOVIE", movie.id, "TMDB", "9300015")])
    with collect_link_skips() as skips:
        await _upsert_external_ids(db, _Staging(db), [("MOVIE", movie.id, "TMDB", "9300015")])

    assert skips.identity_count == 0
    assert skips.count == 0


async def test_two_homonymous_people_lose_one_tmdb_id_and_it_is_counted(db):
    """End to end, on the payload the issue was written about.

    Two *different* TMDB people whose names slugify to the same string go
    through ``_resolve_people``, which merges them into one ``people`` row (the
    2026-09-12 decision: homonyms stay one row).  Only one of the two ids fits
    under ``uq_item_source`` — and that loss is exactly what used to be
    invisible.
    """
    people = [
        BulkPerson(
            source="TMDB",
            external_id=external_id,
            name="Chris Nolan",
            slug="identity-skip-homonym",
            profile_url=None,
            role="DIRECTOR",
            character_name=None,
            billing_order=None,
        )
        for external_id in ("9300020", "9300021")
    ]

    with collect_link_skips() as skips:
        await bulk_load_items(
            db,
            _SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-skip-homonym-movie", "Homonyms"),
                    external_id="9300022",
                    people=people,
                )
            ],
        )

    merged = await db.execute(select(Person.id).where(Person.slug == "identity-skip-homonym"))
    person_id = merged.scalar_one()  # one row, not two — the decision, asserted

    assert skips.identity_count == 1
    skip = skips.identity_skips[0]
    assert (skip.item_type, skip.source, skip.item_id) == ("PERSON", "TMDB", person_id)
    assert {skip.kept_external_id, skip.dropped_external_id} == {"9300020", "9300021"}
    # The person is resolvable by one id and permanently unresolvable by the
    # other — which is the damage the counter exists to report.
    linked = await _linked_id(db, "PERSON", person_id, "TMDB")
    assert linked == skip.kept_external_id


async def test_the_pre_check_still_costs_a_single_query(db):
    """The new signal is another ``OR`` branch, never another round trip.

    ``bulk_load`` exists for its round-trip budget; instrumentation that taxed
    it would be paying with the thing being instrumented.  Two ``SELECT``s
    against ``external_ids`` per batch — the claim pre-check and issue #23's
    identity resolution — no matter how big the batch is.
    """

    def batch(prefix: str, size: int) -> list[BulkItem]:
        return [
            BulkItem(
                data=_movie_payload(f"identity-roundtrip-{prefix}-{i}", f"Round {i}"),
                external_id=f"9301{prefix}{i:02d}",
            )
            for i in range(size)
        ]

    def selects(recorder: _StatementRecorder) -> list[str]:
        return [
            statement
            for statement in recorder.statements
            if "external_ids" in statement and statement.lstrip().upper().startswith("SELECT")
        ]

    with _StatementRecorder() as small:
        await bulk_load_items(db, _SPEC, batch("3", 3))
    with _StatementRecorder() as large:
        await bulk_load_items(db, _SPEC, batch("9", 9))

    assert len(selects(small)) == len(selects(large)) == 2, (selects(small), selects(large))
    pre_check = [
        s for s in selects(small) if s.lstrip().startswith("SELECT external_ids.item_type")
    ]
    assert len(pre_check) == 1
    # Both unique keys read in that one statement.
    assert "external_ids.item_id" in pre_check[0]


# ── The number reaches the sync response ─────────────────────────────────────


def test_the_admin_sync_response_carries_the_counter():
    """Last leg of the road it shares with ``skipped_links``.

    ``POST /admin/sync/{type}`` builds ``SyncResponse(type=type, **result)``,
    and the workflow reads ``.skipped_identities`` off that JSON to raise its
    ``::warning::``.  A field Pydantic did not declare would be dropped
    silently and the annotation would never fire.
    """
    response = SyncResponse(
        type="movie",
        synced=3,
        errors=0,
        offset=0,
        duration_s=1.0,
        people_errors=0,
        skipped_links=1,
        skipped_identities=2,
    )

    assert response.skipped_identities == 2
    assert response.model_dump()["skipped_identities"] == 2
    # Defaulted, like the other two counters: a job that omits it must not 500.
    omitted = SyncResponse(type="book", synced=0, errors=0, offset=0, duration_s=0.1)
    assert omitted.skipped_identities == 0
