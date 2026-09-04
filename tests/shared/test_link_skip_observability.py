"""Issue #22 — the skipped-link counter for both ``external_ids`` write paths.

The bug under test is an *absence*: when the
``(item_type, source, external_id)`` triple a caller wants is already claimed
by a **different** item of the same type, both write paths return the incumbent
row and carry on.  The item lands in its table with no link, and nothing —
exception, counter, log line — says so.  That exact blindness produced issues
#7, #15 and #20, each one found by accident months later.

What has to hold, and is asserted below:

1. **Idempotency stays silent.**  The same TMDB person in cast and crew, a
   re-run of the same slice: the pre-check fires but nothing is lost.  If those
   were counted the number would be pure noise and nobody would look at it.
2. **A stolen link is counted and logged**, naming the triple, the pretender
   and the incumbent — on the per-item path *and* on the batch path, both
   against a pre-existing row and against a collision inside a single batch.
3. **Outside a collector it is a no-op.**  Search fan-out, ``GET /movies/{slug}``
   and ``/similar`` hit the same helper and must neither pay nor fail.
4. **The batch path did not buy this with an extra round trip** — the claim
   pre-check reads one more *column*, not one more query.  The batch route
   exists for its round-trip budget (``backlogg/shared/bulk_load.py`` docstring)
   and instrumentation that taxed it would be a bad trade.
5. **A sync job reports it**, which is the whole point: the number has to reach
   ``POST /admin/sync/{type}``'s response while the run is still going.
"""

import logging
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select

from backlogg.games.models import Game
from backlogg.movies import repository as movies_repo
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
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
    record_link_skip,
    upsert_external_id,
)
from backlogg.shared.models import Person
from tests.shared.test_bulk_load import _StatementRecorder

_SPEC = movies_repo.MOVIE_BULK_SPEC


def _now() -> datetime:
    return datetime.now(UTC)


def _movie_payload(slug: str, title: str) -> dict:
    """Minimal payload with the shape ``movie_to_dict`` produces."""
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


async def _movie(db, slug: str, title: str = "Skip Movie") -> Movie:
    movie = Movie(
        title=title,
        slug=slug,
        release_date=date(2019, 5, 4),
        last_synced_at=_now(),
    )
    db.add(movie)
    await db.flush()
    return movie


async def _movie_by_slug(db, slug: str) -> Movie:
    result = await db.execute(select(Movie).where(Movie.slug == slug))
    return result.scalar_one()


@contextmanager
def _captured_warnings():
    """Capture ``external_ids``' own warnings, robust to the rest of the suite.

    A handler on the module logger instead of ``caplog``: another test may have
    left logging globally disabled, which would silently empty the assertion
    (same reasoning as ``tests/shared/test_bulk_load.py``).
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


async def test_relinking_the_same_item_is_idempotent_and_counts_nothing(db):
    """The case the pre-check was written for must not show up in the counter.

    The same TMDB person appears in cast *and* crew of one movie, and a re-run
    of a slice re-offers links that already exist.  Both reach the same
    ``existing_row is not None`` branch as a genuine loss — the discriminant is
    ``item_id``.
    """
    movie = await _movie(db, "link-skip-idempotent")
    with collect_link_skips() as skips:
        first = await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9100001")
        second = await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9100001")

    assert second.id == first.id
    assert skips.count == 0
    assert skips.skips == []


async def test_a_link_claimed_by_another_item_is_counted(db):
    """The loss itself: the pretender's row exists and never gets its link."""
    incumbent = await _movie(db, "link-skip-incumbent")
    pretender = await _movie(db, "link-skip-pretender")

    with collect_link_skips() as skips:
        returned = await upsert_external_id(db, "MOVIE", incumbent.id, "TMDB", "9100002")
        assert skips.count == 0  # the first claim is not a skip
        returned = await upsert_external_id(db, "MOVIE", pretender.id, "TMDB", "9100002")

    # First claim still wins — this issue instruments the loss, it does not
    # change who owns the link (that is a data decision, see progress notes).
    assert returned.item_id == incumbent.id
    assert skips.count == 1
    skip = skips.skips[0]
    assert skip.item_type == "MOVIE"
    assert skip.source == "TMDB"
    assert skip.external_id == "9100002"
    assert skip.attempted_item_id == pretender.id
    assert skip.claimed_by_item_id == incumbent.id

    # And the pretender really is unlinked, which is what makes it invisible.
    orphan = await db.execute(
        select(func.count())
        .select_from(ExternalId)
        .where(ExternalId.item_type == "MOVIE", ExternalId.item_id == pretender.id)
    )
    assert orphan.scalar_one() == 0


async def test_a_skipped_link_is_logged_with_both_item_ids(db):
    """The log line has to name the triple, the pretender and the incumbent.

    Without both ids the line is unactionable: it says something was lost but
    not which row to look at.
    """
    incumbent = await _movie(db, "link-skip-logged-incumbent")
    pretender = await _movie(db, "link-skip-logged-pretender")
    await upsert_external_id(db, "MOVIE", incumbent.id, "TMDB", "9100003")

    with _captured_warnings() as records:
        await upsert_external_id(db, "MOVIE", pretender.id, "TMDB", "9100003")

    # ``\b`` anchors the ids: a plain substring check would let item_id=1 match
    # inside item_id=12 and turn a wrong log line into a passing assertion.
    wanted = re.compile(rf"wanted by item_id={pretender.id}\b")
    claimed = re.compile(rf"claimed by item_id={incumbent.id}\b")
    messages = [record.getMessage() for record in records]
    assert any(
        "9100003" in message and wanted.search(message) and claimed.search(message)
        for message in messages
    ), messages


async def test_a_person_and_a_movie_sharing_a_tmdb_id_is_not_a_skip(db):
    """Issue #20's fix must not be re-reported as a loss by issue #22's counter.

    TMDB numbers people and movies in independent sequences, so id 9100004 is
    legitimately both.  ``uq_external_id`` carries ``item_type`` since
    migration 0036 and both rows coexist — nothing is skipped.
    """
    person = Person(name="Skip Collider", slug="skip-collider", last_synced_at=_now())
    db.add(person)
    await db.flush()
    movie = await _movie(db, "link-skip-cross-type")

    with collect_link_skips() as skips:
        await upsert_external_id(db, "PERSON", person.id, "TMDB", "9100004")
        await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "9100004")

    assert skips.count == 0


# ── No-op outside the collector ──────────────────────────────────────────────


async def test_upsert_outside_a_collector_still_returns_the_incumbent(db):
    """On-demand traffic pays nothing: no collector, no failure, same result."""
    incumbent = await _movie(db, "link-skip-nocollector-incumbent")
    pretender = await _movie(db, "link-skip-nocollector-pretender")
    await upsert_external_id(db, "MOVIE", incumbent.id, "TMDB", "9100005")

    # No ``collect_link_skips`` block anywhere in this call stack.
    returned = await upsert_external_id(db, "MOVIE", pretender.id, "TMDB", "9100005")
    assert returned.item_id == incumbent.id

    # A collector opened *afterwards* starts empty — the earlier skip is not
    # retroactively attributed to it.
    with collect_link_skips() as skips:
        pass
    assert skips.count == 0


def test_record_link_skip_without_a_collector_is_a_no_op():
    """The recorder is safe to call from anywhere, collector or not."""
    record_link_skip("MOVIE", "TMDB", "9100006", 1, 2)  # must not raise


def test_collectors_do_not_leak_into_each_other():
    """Each block gets its own counter and the previous one is restored.

    ``ContextVar`` + token reset is what makes two concurrent jobs (and the
    ``asyncio.gather`` fan-outs inside them) keep separate numbers.
    """
    with collect_link_skips() as outer:
        record_link_skip("MOVIE", "TMDB", "9100007", 1, 2)
        with collect_link_skips() as inner:
            record_link_skip("MOVIE", "TMDB", "9100008", 3, 4)
        assert inner.count == 1
        record_link_skip("MOVIE", "TMDB", "9100009", 5, 6)

    assert outer.count == 2
    assert [skip.external_id for skip in outer.skips] == ["9100007", "9100009"]


def test_the_detail_list_is_capped_but_the_count_is_not():
    """A systemic failure during a 118.850-item run must not grow a list."""
    with collect_link_skips() as skips:
        for i in range(MAX_TRACKED_LINK_SKIPS + 5):
            record_link_skip("MOVIE", "TMDB", str(i), 1, 2)

    assert skips.count == MAX_TRACKED_LINK_SKIPS + 5
    assert len(skips.skips) == MAX_TRACKED_LINK_SKIPS


# ── Batch path (``_upsert_external_ids``) ────────────────────────────────────


async def test_batch_link_claimed_by_an_existing_row_is_counted(db):
    """The batch pre-check drops the pair — now it says so."""
    first = await bulk_load_items(
        db,
        _SPEC,
        [
            BulkItem(
                data=_movie_payload("link-skip-batch-first", "Batch First"), external_id="9200001"
            )
        ],
    )
    assert first.written == 1
    incumbent = await _movie_by_slug(db, "link-skip-batch-first")

    with collect_link_skips() as skips:
        second = await bulk_load_items(
            db,
            _SPEC,
            [
                BulkItem(
                    data=_movie_payload("link-skip-batch-second", "Batch Second"),
                    external_id="9200001",
                )
            ],
        )
    assert second.written == 1
    pretender = await _movie_by_slug(db, "link-skip-batch-second")

    assert skips.count == 1
    skip = skips.skips[0]
    assert (skip.item_type, skip.source, skip.external_id) == ("MOVIE", "TMDB", "9200001")
    assert skip.attempted_item_id == pretender.id
    assert skip.claimed_by_item_id == incumbent.id

    holder = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == "MOVIE",
            ExternalId.source == "TMDB",
            ExternalId.external_id == "9200001",
        )
    )
    assert holder.scalar_one() == incumbent.id


async def test_rerunning_the_same_batch_counts_no_skip(db):
    """Idempotency on the batch path too — the nightly job re-offers links."""

    def build() -> list[BulkItem]:
        return [
            BulkItem(
                data=_movie_payload("link-skip-batch-idem", "Batch Idem"),
                external_id="9200002",
                people=[
                    BulkPerson(
                        source="TMDB",
                        external_id="9200003",
                        name="Batch Idem Actor",
                        slug="batch-idem-actor",
                        profile_url=None,
                        role="ACTOR",
                        character_name="Someone",
                        billing_order=0,
                    )
                ],
            )
        ]

    await bulk_load_items(db, _SPEC, build())
    with collect_link_skips() as skips:
        await bulk_load_items(db, _SPEC, build())

    assert skips.count == 0


async def test_two_items_of_one_batch_fighting_over_a_triple_are_counted(db):
    """The collision that never touches the database at all.

    Batch de-duplication resolves ``(item_type, source, external_id)`` in
    memory before the ``SELECT``, so this loss used to happen without a single
    query being able to reveal it.  First wins, exactly as a sequential
    per-item run would, and the loser is now counted.
    """
    with collect_link_skips() as skips:
        outcome = await bulk_load_items(
            db,
            _SPEC,
            [
                BulkItem(
                    data=_movie_payload("link-skip-intra-a", "Intra A"),
                    external_id="9200004",
                ),
                BulkItem(
                    data=_movie_payload("link-skip-intra-b", "Intra B"),
                    external_id="9200004",
                ),
            ],
        )

    assert outcome.written == 2
    winner = await _movie_by_slug(db, "link-skip-intra-a")
    loser = await _movie_by_slug(db, "link-skip-intra-b")

    assert skips.count == 1
    assert skips.skips[0].attempted_item_id == loser.id
    assert skips.skips[0].claimed_by_item_id == winner.id

    holder = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == "MOVIE",
            ExternalId.source == "TMDB",
            ExternalId.external_id == "9200004",
        )
    )
    assert holder.scalar_one() == winner.id


async def test_an_exact_duplicate_row_inside_one_batch_is_not_a_skip(db):
    """The intra-batch guard itself: same triple **and** same item, no loss.

    Driven straight at ``_upsert_external_ids`` on purpose.  Neither of its two
    production callers can reach this branch today — ``bulk_load_items``
    de-duplicates by slug before building its rows, and ``_resolve_people``
    keys ``slug_of_key`` on ``(source, external_id)`` — so going through
    ``bulk_load_items`` (which is what the sibling test below does) exercises
    the *contract* but leaves the ``incumbent[1] != row[1]`` guard itself
    uncovered: mutating it to ``elif True`` did not fail a single test.

    The guard still has to be right.  It is the batch half of the very
    discriminant this issue is about, the helper is reachable by any future
    caller, and a wrong answer here would report phantom losses on a batch that
    lost nothing — which is worse than no counter at all, because an operator
    who learns the number lies stops reading it.
    """
    incumbent = await _movie(db, "link-skip-exact-dup")
    duplicated = ("MOVIE", incumbent.id, "TMDB", "9200007")

    with collect_link_skips() as skips:
        await _upsert_external_ids(db, _Staging(db), [duplicated, duplicated])

    assert skips.count == 0

    holder = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == "MOVIE",
            ExternalId.source == "TMDB",
            ExternalId.external_id == "9200007",
        )
    )
    assert holder.scalar_one() == incumbent.id


async def test_two_items_fighting_over_a_triple_inside_one_batch_are_counted(db):
    """The other side of the same guard, at the same level: different item, loss.

    Same call, one field changed.  Together the two tests pin the branch to
    ``item_id`` and nothing else — flipping the condition either way breaks one
    of them.
    """
    incumbent = await _movie(db, "link-skip-exact-dup-winner")
    pretender = await _movie(db, "link-skip-exact-dup-loser")

    with collect_link_skips() as skips:
        await _upsert_external_ids(
            db,
            _Staging(db),
            [
                ("MOVIE", incumbent.id, "TMDB", "9200008"),
                ("MOVIE", pretender.id, "TMDB", "9200008"),
            ],
        )

    assert skips.count == 1
    assert skips.skips[0].attempted_item_id == pretender.id
    assert skips.skips[0].claimed_by_item_id == incumbent.id


async def test_the_same_item_offered_twice_in_a_batch_is_not_a_skip(db):
    """Two credits of the same person in one batch: de-duplicated, not lost."""
    person = BulkPerson(
        source="TMDB",
        external_id="9200005",
        name="Batch Dual Role",
        slug="batch-dual-role",
        profile_url=None,
        role="ACTOR",
        character_name="Someone",
        billing_order=0,
    )
    with collect_link_skips() as skips:
        await bulk_load_items(
            db,
            _SPEC,
            [
                BulkItem(
                    data=_movie_payload("link-skip-dual", "Dual"),
                    external_id="9200006",
                    people=[person, replace(person, role="DIRECTOR")],
                )
            ],
        )

    assert skips.count == 0


async def test_the_claim_pre_check_still_costs_a_single_query(db):
    """The extra signal is one more *column*, never one more round trip.

    ``bulk_load``'s reason to exist is its round-trip budget (35-75 per item
    down to a handful per batch).  Reading ``item_id`` in the pre-check that
    was already being issued keeps that budget intact; a second ``SELECT``
    would have paid for the instrumentation with the thing being instrumented.
    """
    items = [
        BulkItem(
            data=_movie_payload(f"link-skip-roundtrip-{i}", f"Round Trip {i}"),
            external_id=f"920010{i}",
        )
        for i in range(3)
    ]
    with _StatementRecorder() as recorder:
        await bulk_load_items(db, _SPEC, items)

    selects = [
        statement
        for statement in recorder.statements
        if "external_ids" in statement and statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 1, selects
    assert "item_id" in selects[0]


# ── The number reaches the sync response ─────────────────────────────────────


def _session_factory(db):
    """Stand-in for ``async_session_factory`` yielding the test session.

    Keeps the job inside the fixture's SAVEPOINT so its commits are rolled back
    at teardown, same trick as ``tests/test_backfill_credits_targeted.py``.
    """
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


async def test_sync_games_reports_the_links_it_could_not_write(db):
    """End to end on a real job: the loss shows up in the returned dict.

    The scenario is the realistic one, not a contrived collision: IGDB game
    9300001 was ingested when its name slugified to ``link-skip-game-old``;
    the game has since been renamed, so this slice writes a **second** row
    under the new slug and that row can never take the external id — the old
    one holds it.  Before issue #22 the job returned ``errors: 0`` and the
    operator had no way to tell.
    """
    stale = Game(
        title="Link Skip Game Old",
        slug="link-skip-game-old",
        game_type="MAIN_GAME",
        last_synced_at=_now(),
    )
    db.add(stale)
    await db.flush()
    await upsert_external_id(db, "GAME", stale.id, "IGDB", "9300001")
    await db.flush()

    raw = [
        {
            "id": 9300001,
            "name": "Link Skip Game New",
            "slug": "link-skip-game-new",
            "game_type": 0,
        }
    ]

    with (
        patch.object(
            sync_jobs._igdb_client, "get_top_games", new_callable=AsyncMock, return_value=raw
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=1)

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["skipped_links"] == 1

    # The new row is really there and really unlinked.
    renamed = await _movie_or_game_id(db, "link-skip-game-new")
    orphan = await db.execute(
        select(func.count())
        .select_from(ExternalId)
        .where(ExternalId.item_type == "GAME", ExternalId.item_id == renamed)
    )
    assert orphan.scalar_one() == 0


async def _movie_or_game_id(db, slug: str) -> int:
    result = await db.execute(select(Game.id).where(Game.slug == slug))
    return result.scalar_one()


async def test_a_clean_sync_reports_zero_skipped_links(db):
    """The key is always present, so the response schema never has to guess."""
    raw = [
        {
            "id": 9300002,
            "name": "Link Skip Game Clean",
            "slug": "link-skip-game-clean",
            "game_type": 0,
        }
    ]
    with (
        patch.object(
            sync_jobs._igdb_client, "get_top_games", new_callable=AsyncMock, return_value=raw
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
    ):
        result = await sync_jobs.sync_games(slice_size=1)

    assert result["synced"] == 1
    assert result["skipped_links"] == 0
