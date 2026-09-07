"""Issues #23 and #25 — the external id is the identity, and the work list knows it.

**#23.** Every catalog write path resolved items by slug
(``ON CONFLICT ("slug")``) while ``external_ids`` resolved them by
``(item_type, source, external_id)``.  A rename at the source makes the two
disagree forever: the new slug matches no row, a *second* row is written, and
it can never take the external id because the old row still holds it.  The
result is a permanent duplicate plus an item frozen out of the refresh
rotation, of ``get_credit_gaps`` and of every lookup by external id.

**#25.** ``_unlinked_targets_stmt`` decided a ``seed_target`` was done as soon
as *some* row carried its triple, without checking that the row pointed at a
real item.  A target whose triple was held by a link pointing nowhere counted
as converged: out of the work list, no ``attempts``, absent from ``pending``
and from ``stuck``.  The two issues are one change on purpose — the item_id
check is only safe once the identity is resolved by external id, because
otherwise a re-opened target would retry forever without ever being able to
link, which is worse than the silence it replaces.

What is asserted here:

1. A renamed item **updates its row** — same ``id``, new slug, one row — on the
   batch route, on the per-item fallback of the batch route, and on the
   on-demand route, for all four content types.
2. The measured case: TMDB series 284753.
3. The rename does not blow up when the new slug is taken: the collision is
   resolved deterministically, never with an ``IntegrityError``.
4. ``skipped_links`` (issue #22) still counts what is genuinely lost.
5. A seed target whose triple points at no item stays workable and burns its
   attempts; one that points at its own item is done.
"""

import logging
from contextlib import contextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select, text

from backlogg.books import repository as books_repo
from backlogg.books.models import Book
from backlogg.games import repository as games_repo
from backlogg.games.models import Game
from backlogg.movies import repository as movies_repo
from backlogg.movies import service as movies_service
from backlogg.movies.models import Movie
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import (
    SeedTargetRow,
    count_seed_target_progress,
    get_pending_seed_targets,
    mark_seed_targets_attempted,
    upsert_seed_targets,
)
from backlogg.series import repository as series_repo
from backlogg.series.models import Series
from backlogg.shared import identity
from backlogg.shared.bulk_load import BulkItem, bulk_load_items
from backlogg.shared.external_ids import ExternalId, collect_link_skips, upsert_external_id
from backlogg.shared.identity import align_slugs_to_external_ids
from backlogg.shared.slugs import titled_slug

_MOVIE_SPEC = movies_repo.MOVIE_BULK_SPEC
_SERIES_SPEC = series_repo.SERIES_BULK_SPEC


def _now() -> datetime:
    return datetime.now(UTC)


def _movie_payload(slug: str, title: str) -> dict:
    """The shape ``movie_to_dict`` produces, trimmed to what the tests read."""
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "release_date": date(2010, 7, 16),
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
        "last_synced_at": _now(),
        "genres": [],
    }


def _series_payload(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "first_air_date": date(2025, 5, 4),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 6,
        "status": "Ended",
        "original_language": "hi",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
    }


def _book_payload(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "first_publish_date": date(2021, 9, 14),
        "original_language": "en",
        "poster_url": None,
        "isbn": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
    }


def _game_payload(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": None,
        "release_date": date(2017, 3, 3),
        "game_type": "MAIN_GAME",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": _now(),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


async def _count(db, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    return (await db.execute(stmt)).scalar_one()


async def _row(db, model, item_id: int) -> tuple[str, str]:
    """``(slug, title)`` read straight from the database, bypassing the ORM cache."""
    result = await db.execute(
        select(model.slug, model.title)
        .where(model.id == item_id)
        .execution_options(populate_existing=True)
    )
    return tuple(result.one())


@contextmanager
def _identity_warnings():
    """Capture ``backlogg.shared.identity``'s own warnings.

    A handler on the module logger instead of ``caplog``: another test may have
    left logging globally disabled, which would empty the assertion in silence
    (same reasoning as ``tests/shared/test_bulk_load.py``).  These messages are
    what tells the three "kept the old slug" branches apart, and each of them
    means something different to whoever reads the log during a seeding run.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.NOTSET)
    module_logger = logging.getLogger("backlogg.shared.identity")
    module_logger.addHandler(handler)
    previous_level = module_logger.level
    module_logger.setLevel(logging.INFO)
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


async def _link_holder(db, item_type: str, source: str, external_id: str) -> int | None:
    result = await db.execute(
        select(ExternalId.item_id).where(
            ExternalId.item_type == item_type,
            ExternalId.source == source,
            ExternalId.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


# ── #23: a rename updates the row it always was ──────────────────────────────


async def test_the_batch_route_follows_the_external_id_when_the_title_changes(db):
    """One id, one row: the batch writes the new title onto the old row.

    Before this fix the second batch inserted a second movie (the new slug
    matched nothing) and that movie could never be linked — the triple was
    already claimed.  ``skipped_links`` had to be 1 for a scenario in which
    nothing was actually unavailable, which is the tell that the loss was
    self-inflicted.
    """
    await bulk_load_items(
        db,
        _MOVIE_SPEC,
        [
            BulkItem(
                data=_movie_payload("identity-batch-old-2010", "Old Title"), external_id="931001"
            )
        ],
    )
    original_id = await _link_holder(db, "MOVIE", "TMDB", "931001")
    assert original_id is not None

    with collect_link_skips() as skips:
        outcome = await bulk_load_items(
            db,
            _MOVIE_SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-batch-new-2010", "New Title"),
                    external_id="931001",
                )
            ],
        )

    assert outcome.written == 1
    # Nothing was lost, so nothing may be reported as lost.
    assert skips.count == 0
    assert await _link_holder(db, "MOVIE", "TMDB", "931001") == original_id
    assert await _row(db, Movie, original_id) == ("identity-batch-new-2010", "New Title")
    assert await _count(db, Movie, slug="identity-batch-old-2010") == 0
    assert await _count(db, ExternalId, item_type="MOVIE", item_id=original_id) == 1


async def test_the_on_demand_route_follows_the_external_id_when_the_title_changes(db):
    """Same rule through the per-item upsert the on-demand paths call.

    ``GET /movies/{slug}``, the search fan-out, ``/similar`` and ``trending``
    all reach the catalog through ``upsert_movie`` + ``upsert_external_id``.
    Passing the external id is what makes them resolve identity, and the two
    routes must agree — otherwise the same TMDB id would mean two different
    rows depending on which door it came through.
    """
    movie = await movies_repo.upsert_movie(
        db, _movie_payload("identity-item-old-2010", "Old Title"), external_id="931002"
    )
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "931002")

    with collect_link_skips() as skips:
        renamed = await movies_repo.upsert_movie(
            db, _movie_payload("identity-item-new-2010", "New Title"), external_id="931002"
        )
        await upsert_external_id(db, "MOVIE", renamed.id, "TMDB", "931002")

    assert renamed.id == movie.id
    assert skips.count == 0
    assert await _row(db, Movie, movie.id) == ("identity-item-new-2010", "New Title")
    assert await _count(db, Movie, slug="identity-item-old-2010") == 0
    assert await _count(db, ExternalId, item_type="MOVIE", item_id=movie.id) == 1


@pytest.mark.parametrize(
    ("upsert", "model", "payload", "item_type", "source", "external_id"),
    [
        (series_repo.upsert_series, Series, _series_payload, "SERIES", "TMDB", "931003"),
        (books_repo.upsert_book, Book, _book_payload, "BOOK", "OPEN_LIBRARY", "OL931004W"),
        (games_repo.upsert_game, Game, _game_payload, "GAME", "IGDB", "931005"),
    ],
)
async def test_every_content_type_resolves_by_external_id(
    db, upsert, model, payload, item_type, source, external_id
):
    """The rule is per catalog table, so all four write paths must carry it.

    Movies are covered by the two tests above; this pins the other three, each
    against its own source, because a fix applied to three tables out of four
    is the shape of every issue in this family (#7, #15, #18, #20).
    """
    original = await upsert(
        db, payload(f"identity-{item_type.lower()}-old", "Old"), external_id=external_id
    )
    await upsert_external_id(db, item_type, original.id, source, external_id)

    renamed = await upsert(
        db, payload(f"identity-{item_type.lower()}-new", "New"), external_id=external_id
    )
    await upsert_external_id(db, item_type, renamed.id, source, external_id)

    assert renamed.id == original.id
    assert await _row(db, model, original.id) == (f"identity-{item_type.lower()}-new", "New")
    assert await _count(db, model, slug=f"identity-{item_type.lower()}-old") == 0
    assert await _link_holder(db, item_type, source, external_id) == original.id


async def test_the_per_item_fallback_of_the_batch_route_resolves_by_external_id(db):
    """The fallback is a real write path, not a decoration.

    A batch that fails is reprocessed item by item by
    ``_write_items_individually`` (feature 84, decision D2).  If identity were
    resolved only in the batch, a slice that fell back would keep forking
    duplicates — and the fallback runs exactly when things are already going
    wrong, which is the worst moment to lose catalog silently.
    """
    movie = await movies_repo.upsert_movie(
        db, _movie_payload("identity-fallback-old-2010", "Old Title"), external_id="931006"
    )
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "931006")
    await db.commit()

    synced, errors, people_errors = await _write_items_individually_wrapper(
        db,
        [
            BulkItem(
                data=_movie_payload("identity-fallback-new-2010", "New Title"),
                external_id="931006",
            )
        ],
    )

    assert (synced, errors, people_errors) == (1, 0, 0)
    assert await _row(db, Movie, movie.id) == ("identity-fallback-new-2010", "New Title")
    assert await _count(db, Movie, slug="identity-fallback-old-2010") == 0
    assert await _link_holder(db, "MOVIE", "TMDB", "931006") == movie.id


async def _write_items_individually_wrapper(db, items):
    return await sync_jobs._write_items_individually(db, _MOVIE_SPEC, items, "test_identity")


async def test_the_tmdb_284753_regression(db):
    """The case measured on the dev database on 2026-09-04.

    TMDB series 284753 was seeded as «Operation Safed Sagar: The Highest Air
    Force Mission» (``series.id=4``, holding the link) and later renamed to
    «... The Untold Story of the Kargil War».  The refresh slice wrote
    ``series.id=1265`` under the new slug, unlinked and duplicated, and the
    only reason anyone noticed was the ``skipped_links=1`` that issue #22 had
    just added.

    Reproduced through the same route that produced it — the seeding batch —
    with the real titles, and asserting the three things that were wrong: one
    row, the same row, and the link still on it.
    """
    old_title = "Operation Safed Sagar: The Highest Air Force Mission"
    new_title = "Operation Safed Sagar: The Untold Story of the Kargil War"
    old_slug = titled_slug(old_title, 2025, "TMDB", "284753")
    new_slug = titled_slug(new_title, 2025, "TMDB", "284753")
    assert old_slug != new_slug  # the premise of the bug

    await bulk_load_items(
        db,
        _SERIES_SPEC,
        [BulkItem(data=_series_payload(old_slug, old_title), external_id="284753")],
    )
    seeded_id = await _link_holder(db, "SERIES", "TMDB", "284753")

    with collect_link_skips() as skips:
        await bulk_load_items(
            db,
            _SERIES_SPEC,
            [BulkItem(data=_series_payload(new_slug, new_title), external_id="284753")],
        )

    assert skips.count == 0
    assert await _count(db, Series, title=new_title) == 1
    assert await _count(db, Series, title=old_title) == 0
    assert await _row(db, Series, seeded_id) == (new_slug, new_title)
    assert await _link_holder(db, "SERIES", "TMDB", "284753") == seeded_id


async def test_sync_games_renaming_a_game_updates_its_row(db):
    """End to end on a real job, the counterpart of the issue-#22 test.

    ``tests/shared/test_link_skip_observability.py`` used this very scenario to
    show a link being lost.  It is not lost any more: the slice updates the
    row that holds IGDB 9300001 and reports ``skipped_links=0``.
    """
    stale = Game(
        title="Identity Game Old",
        slug="identity-game-old",
        game_type="MAIN_GAME",
        last_synced_at=_now(),
    )
    db.add(stale)
    await db.flush()
    await upsert_external_id(db, "GAME", stale.id, "IGDB", "9310001")
    await db.flush()

    raw = [
        {
            "id": 9310001,
            "name": "Identity Game New",
            "slug": "identity-game-new",
            "game_type": 0,
        }
    ]
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(
            sync_jobs._igdb_client, "get_top_games", new_callable=AsyncMock, return_value=raw
        ),
        patch(
            "backlogg.scheduler.jobs.async_session_factory",
            new=lambda *args, **kwargs: session_cm,
        ),
    ):
        result = await sync_jobs.sync_games(slice_size=1)

    assert result["synced"] == 1
    assert result["errors"] == 0
    assert result["skipped_links"] == 0
    assert await _count(db, Game, slug="identity-game-old") == 0
    assert await _row(db, Game, stale.id) == ("identity-game-new", "Identity Game New")
    assert await _link_holder(db, "GAME", "IGDB", "9310001") == stale.id


async def test_the_on_demand_service_renames_instead_of_duplicating(db):
    """The whole on-demand chain, not just the repository call.

    A user asks for the *new* slug, the catalog does not have it, the service
    falls back to TMDB and gets back an id it already knows.  The proof that
    the service passes that id down is that the old row is renamed rather than
    duplicated.
    """
    stale = await movies_repo.upsert_movie(db, _movie_payload("old-name-2010", "Old Name"))
    await upsert_external_id(db, "MOVIE", stale.id, "TMDB", "27205")

    detail = {
        "id": 27205,
        "title": "Inception",
        "original_title": "Inception",
        "overview": "A mind-bending thriller.",
        "release_date": "2010-07-16",
        "runtime": 148,
        "original_language": "en",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 160000000,
        "revenue": 836000000,
        "status": "Released",
        "vote_average": 8.8,
        "vote_count": 30000,
        "genres": [],
    }
    with (
        patch.object(
            movies_service._tmdb,
            "search_movie",
            new_callable=AsyncMock,
            return_value=[{"id": 27205}],
        ),
        patch.object(
            movies_service._tmdb, "get_movie_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value={"cast": [], "crew": []},
        ),
    ):
        result = await movies_service.get_movie(db, "inception-2010")

    assert result.slug == "inception-2010"
    assert await _count(db, Movie, slug="old-name-2010") == 0
    assert await _row(db, Movie, stale.id) == ("inception-2010", "Inception")
    assert await _link_holder(db, "MOVIE", "TMDB", "27205") == stale.id


# ── #23: what happens when the new slug is not free ──────────────────────────


async def test_a_rename_into_a_slug_another_item_owns_keeps_the_old_slug(db):
    """The collision is resolved by *not* renaming — never by raising.

    ``uq_movies_slug`` is a real constraint and the incumbent of the target
    slug is a legitimate, linked item of its own.  Stealing its name would
    mis-slug it; letting the ``UPDATE`` raise would take the whole slice down.
    So the renamed item keeps its stored slug and is still updated in place:
    the cost is a stale URL, and the alternative (the pre-#23 behaviour) was a
    permanent duplicate.
    """
    squatter = await movies_repo.upsert_movie(
        db, _movie_payload("identity-shared-slug-2010", "Squatter"), external_id="931011"
    )
    await upsert_external_id(db, "MOVIE", squatter.id, "TMDB", "931011")
    renamer = await movies_repo.upsert_movie(
        db, _movie_payload("identity-renamer-old-2010", "Renamer Old"), external_id="931012"
    )
    await upsert_external_id(db, "MOVIE", renamer.id, "TMDB", "931012")

    with _identity_warnings() as records:
        outcome = await bulk_load_items(
            db,
            _MOVIE_SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-shared-slug-2010", "Renamer New"),
                    external_id="931012",
                )
            ],
        )

    assert outcome.written == 1
    # The collision was *detected*, not survived: the savepoint fallback below
    # would produce the same rows, so without this the test cannot tell the
    # check from the recovery — and only the check keeps the write out of an
    # IntegrityError in the first place.
    messages = [record.getMessage() for record in records]
    assert any(f"already belongs to item_id={squatter.id}" in message for message in messages), (
        messages
    )
    assert not any("rolled back" in message for message in messages), messages
    # The renamed item kept its slug but took the new title, on its own row.
    assert await _row(db, Movie, renamer.id) == ("identity-renamer-old-2010", "Renamer New")
    # The squatter is untouched: same row, same slug, same title, same link.
    assert await _row(db, Movie, squatter.id) == ("identity-shared-slug-2010", "Squatter")
    assert await _link_holder(db, "MOVIE", "TMDB", "931011") == squatter.id
    assert await _link_holder(db, "MOVIE", "TMDB", "931012") == renamer.id
    # And no third row was invented for the collision.
    assert await _count(db, Movie, title="Renamer New") == 1


async def test_two_items_of_one_batch_renaming_into_the_same_slug_keep_theirs(db):
    """A contested slug is nobody's: the outcome cannot depend on fetch order.

    Two ids whose new titles fold to the same slug arrive in one slice.  If the
    first in the list won, the same slice fetched in a different order would
    produce a different catalog — and slices are fetched with
    ``asyncio.gather``.  Neither renames; both are still updated in place.
    """
    first = await movies_repo.upsert_movie(
        db, _movie_payload("identity-race-a-2010", "Race A"), external_id="931013"
    )
    await upsert_external_id(db, "MOVIE", first.id, "TMDB", "931013")
    second = await movies_repo.upsert_movie(
        db, _movie_payload("identity-race-b-2010", "Race B"), external_id="931014"
    )
    await upsert_external_id(db, "MOVIE", second.id, "TMDB", "931014")

    with _identity_warnings() as records:
        outcome = await bulk_load_items(
            db,
            _MOVIE_SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-race-shared-2010", "Race A New"),
                    external_id="931013",
                ),
                BulkItem(
                    data=_movie_payload("identity-race-shared-2010", "Race B New"),
                    external_id="931014",
                ),
            ],
        )

    assert outcome.written == 2
    messages = [record.getMessage() for record in records]
    assert sum("more than one item of this batch" in message for message in messages) == 2, messages
    assert await _row(db, Movie, first.id) == ("identity-race-a-2010", "Race A New")
    assert await _row(db, Movie, second.id) == ("identity-race-b-2010", "Race B New")
    assert await _count(db, Movie, slug="identity-race-shared-2010") == 0
    assert await _link_holder(db, "MOVIE", "TMDB", "931013") == first.id
    assert await _link_holder(db, "MOVIE", "TMDB", "931014") == second.id


async def test_an_admin_locked_title_is_not_renamed_but_still_finds_its_row(db):
    """Feature 49 keeps its promise, and the item still does not fork.

    The slug is derived from the title, so an admin-locked title must not be
    re-slugged by the source.  What the lock cannot do is send the source's
    payload to a *different* row: the identity resolution still points the
    write at the locked item, which then keeps its title and its slug.
    """
    movie = await movies_repo.upsert_movie(
        db, _movie_payload("identity-locked-2010", "Curated Title"), external_id="931015"
    )
    await upsert_external_id(db, "MOVIE", movie.id, "TMDB", "931015")
    await db.execute(
        text("UPDATE movies SET locked_fields = ARRAY['title'] WHERE id = :id"), {"id": movie.id}
    )
    await db.flush()

    await bulk_load_items(
        db,
        _MOVIE_SPEC,
        [
            BulkItem(
                data=_movie_payload("identity-source-title-2010", "Source Title"),
                external_id="931015",
            )
        ],
    )

    assert await _row(db, Movie, movie.id) == ("identity-locked-2010", "Curated Title")
    assert await _count(db, Movie, slug="identity-source-title-2010") == 0
    assert await _link_holder(db, "MOVIE", "TMDB", "931015") == movie.id


async def test_losing_the_race_for_a_slug_is_absorbed_by_the_savepoint(db):
    """The check is not atomic, so the write cannot be allowed to raise.

    Between reading who owns a slug and updating into it, another writer can
    take it — two on-demand requests for the same renamed item, a job racing a
    search fan-out.  The rename runs inside a ``SAVEPOINT``: it rolls back, the
    items keep their stored slugs, the upsert still lands on the right rows and
    nothing propagates.  A rename losing a race must never become a 500 or take
    a 500-item slice down.

    The race is reproduced by making the ownership lookup answer "free" for a
    slug that is not, which is precisely the state the loser of the race reads.
    """
    squatter = await movies_repo.upsert_movie(
        db, _movie_payload("identity-race-taken-2010", "Squatter"), external_id="931021"
    )
    await upsert_external_id(db, "MOVIE", squatter.id, "TMDB", "931021")
    renamer = await movies_repo.upsert_movie(
        db, _movie_payload("identity-race-loser-2010", "Loser Old"), external_id="931022"
    )
    await upsert_external_id(db, "MOVIE", renamer.id, "TMDB", "931022")

    with (
        patch.object(identity, "_slug_owners", new_callable=AsyncMock, return_value={}),
        _identity_warnings() as records,
    ):
        outcome = await bulk_load_items(
            db,
            _MOVIE_SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-race-taken-2010", "Loser New"),
                    external_id="931022",
                )
            ],
        )

    assert outcome.written == 1
    messages = [record.getMessage() for record in records]
    assert any("rolled back" in message for message in messages), messages
    # Both rows survive, each with its own slug and its own link.
    assert await _row(db, Movie, renamer.id) == ("identity-race-loser-2010", "Loser New")
    assert await _row(db, Movie, squatter.id) == ("identity-race-taken-2010", "Squatter")
    assert await _link_holder(db, "MOVIE", "TMDB", "931021") == squatter.id
    assert await _link_holder(db, "MOVIE", "TMDB", "931022") == renamer.id


async def test_a_link_pointing_at_no_item_decides_no_identity(db):
    """A dangling link owns a triple but is not an item, so it resolves nothing.

    ``external_ids`` carries no FK, so a row can outlive its item (a catalog
    row deleted by hand, a half-wiped database).  The identity lookup joins the
    catalog table precisely so such a row cannot redirect a write onto an id
    that does not exist — the item is written normally and the loss of the link
    is reported by the issue-#22 counter, which is the only signal an operator
    can act on.
    """
    orphan_item_id = 2_000_000_010
    db.add(
        ExternalId(item_type="MOVIE", item_id=orphan_item_id, source="TMDB", external_id="931016")
    )
    await db.flush()

    resolved = await align_slugs_to_external_ids(
        db,
        item_type="MOVIE",
        table=Movie.__table__,
        source="TMDB",
        proposed={"931016": "identity-orphan-2010"},
    )
    assert resolved == {}

    with collect_link_skips() as skips:
        outcome = await bulk_load_items(
            db,
            _MOVIE_SPEC,
            [
                BulkItem(
                    data=_movie_payload("identity-orphan-2010", "Orphan Claimed"),
                    external_id="931016",
                )
            ],
        )

    assert outcome.written == 1
    assert skips.count == 1
    assert skips.skips[0].claimed_by_item_id == orphan_item_id


# ── #25: the work list checks where the link points ──────────────────────────


async def test_a_target_whose_triple_points_at_no_item_stays_workable(db):
    """The silence this issue is about: a target counted as done having done nothing.

    The triple ``(MOVIE, TMDB, 932001)`` exists, so the old query took the
    target for converged: gone from ``pending``, never retried, never counted
    in ``stuck``.  Nothing in the three numbers an operator reads showed that
    the catalog was missing an item it had enumerated.
    """
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "932001", vote_count=500, release_year=2010)]
    )
    db.add(
        ExternalId(item_type="MOVIE", item_id=2_000_000_020, source="TMDB", external_id="932001")
    )
    await db.flush()

    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 3) == ["932001"]
    progress = await count_seed_target_progress(db, "MOVIE", "TMDB", 3)
    assert (progress.total, progress.pending, progress.stuck) == (1, 1, 0)

    # And it accumulates attempts, which is what eventually makes it *visible*
    # instead of merely invisible: two conclusive passes retire it as
    # unlinkable, so it leaves the work list through ``stuck``, not silently.
    await mark_seed_targets_attempted(db, "MOVIE", "TMDB", ["932001"], _now())
    await db.flush()
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 2) == ["932001"]

    await mark_seed_targets_attempted(db, "MOVIE", "TMDB", ["932001"], _now())
    await db.flush()
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 2) == []
    retired = await count_seed_target_progress(db, "MOVIE", "TMDB", 2)
    assert (retired.pending, retired.unlinkable, retired.stuck) == (0, 1, 1)


async def test_a_target_linked_to_its_own_item_is_done(db):
    """No regression on convergence: a seeded target must leave the work list.

    This is the other half of the item_id check.  With identity resolved by
    external id (issue #23), the row holding a triple *is* the item that target
    seeds, so "linked to a live item" and "seeded" are the same statement — a
    target must not come back for a second pass just because the query got more
    suspicious.
    """
    await upsert_seed_targets(
        db,
        [
            SeedTargetRow("MOVIE", "TMDB", "932002", vote_count=500, release_year=2010),
            SeedTargetRow("MOVIE", "TMDB", "932003", vote_count=400, release_year=2010),
        ],
    )
    seeded = await movies_repo.upsert_movie(
        db, _movie_payload("identity-target-2010", "Target Movie"), external_id="932002"
    )
    await upsert_external_id(db, "MOVIE", seeded.id, "TMDB", "932002")
    await db.flush()

    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 3) == ["932003"]
    progress = await count_seed_target_progress(db, "MOVIE", "TMDB", 3)
    assert (progress.total, progress.pending, progress.stuck) == (2, 1, 0)


async def test_a_renamed_seeded_target_stays_converged(db):
    """#23 and #25 together: the rename keeps the target out of the work list.

    This is the reason the two issues ship in one branch.  With the item_id
    check but *without* identity by external id, a renamed item would fork a
    second row, the target would come back to the work list and would retry
    forever without ever being able to link — strictly worse than the silence.
    Here the rename updates the seeded row, so the target simply stays done.
    """
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "932004", vote_count=500, release_year=2010)]
    )
    await bulk_load_items(
        db,
        _MOVIE_SPEC,
        [BulkItem(data=_movie_payload("identity-seed-old-2010", "Seed Old"), external_id="932004")],
    )
    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 3) == []

    await bulk_load_items(
        db,
        _MOVIE_SPEC,
        [BulkItem(data=_movie_payload("identity-seed-new-2010", "Seed New"), external_id="932004")],
    )

    assert await get_pending_seed_targets(db, "MOVIE", "TMDB", 10, 3) == []
    progress = await count_seed_target_progress(db, "MOVIE", "TMDB", 3)
    assert (progress.total, progress.pending, progress.stuck) == (1, 0, 0)
    # And it stays converged for the right reason: one row, renamed — not a
    # duplicate keeping the old link alive while the real item drifts away.
    assert await _count(db, Movie, slug="identity-seed-new-2010") == 1
    assert await _count(db, Movie, slug="identity-seed-old-2010") == 0
