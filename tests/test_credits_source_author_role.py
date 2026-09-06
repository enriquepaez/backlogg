"""Tests for feature 74 — SOURCE_AUTHOR / WRITER credits on movies and series.

What is under test:

- the ingestion mappers (``movies.service.map_movie_credits`` and
  ``series.service.map_series_credits``) filter TMDB's ``crew`` by an explicit
  **job** allowlist, never by ``department == "Writing"``: storyboard jobs are
  dropped, ``Story``/``Screenstory``/``Original Story`` never become
  ``SOURCE_AUTHOR``, and a real adaptation yields ``WRITER`` and
  ``SOURCE_AUTHOR`` on *different* people;
- both write paths persist the new roles — the on-demand route
  (``GET /movies/{slug}``, ``GET /series/{slug}``) and the seeding/backfill
  route (``scheduler.jobs``, which goes through ``bulk_load_credits``);
- ``recommendations.repository.get_authorship_works`` links a person's works
  across every ``item_type`` treating ``{AUTHOR, SOURCE_AUTHOR}`` as one
  authorship class, and refuses to emit a bridge for a person with no
  ``AUTHOR`` credit on a book of the catalog (the translator credited with
  ``job: "Book"``).

The mapper tests are pure (no DB, no network). The write-path and query tests
run against the real PostgreSQL test database; every external call is mocked.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from backlogg.books.models import Book
from backlogg.movies import service as movies_service
from backlogg.movies.models import Movie
from backlogg.recommendations import repository as recs_repo
from backlogg.scheduler import jobs as sync_jobs
from backlogg.series import service as series_service
from backlogg.series.models import Series
from backlogg.shared.external_ids import ExternalId
from backlogg.shared.models import Credit, Person

# ── Helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _crew(tmdb_id: int, name: str, job: str) -> dict:
    return {"id": tmdb_id, "name": name, "job": job, "department": "Writing", "profile_path": None}


def _cast(tmdb_id: int, name: str, order: int = 0) -> dict:
    return {
        "id": tmdb_id,
        "name": name,
        "profile_path": None,
        "order": order,
        "character": f"{name} the character",
    }


def _roles_by_name(rows) -> set[tuple[str, str]]:
    return {(row.name, row.role) for row in rows}


async def _persisted_roles(db, item_type: str, item_id: int) -> set[tuple[str, str]]:
    result = await db.execute(
        select(Person.name, Credit.role)
        .join(Person, Person.id == Credit.person_id)
        .where(Credit.item_type == item_type, Credit.item_id == item_id)
    )
    return {(name, role) for name, role in result.all()}


def _session_factory(db):
    """Stand-in for ``async_session_factory`` yielding the test session."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


# ── The mappers: job allowlist, not department ───────────────────────────────


def test_movie_crew_maps_source_author_and_writer_by_job():
    """Every allowlisted job lands on its role; DIRECTOR keeps working."""
    rows = movies_service.map_movie_credits(
        {
            "cast": [_cast(1, "Lead Actor")],
            "crew": [
                _crew(10, "Some Director", "Director"),
                _crew(11, "Novelist", "Novel"),
                _crew(12, "Book Author", "Book"),
                _crew(13, "Short Story Author", "Short Story"),
                _crew(14, "Comic Author", "Comic Book"),
                _crew(15, "Graphic Novelist", "Graphic Novel"),
                _crew(16, "Playwright", "Theatre Play"),
                _crew(18, "Character Creator", "Characters"),
                _crew(20, "Screenplay Writer", "Screenplay"),
                _crew(21, "Plain Writer", "Writer"),
                _crew(22, "Teleplay Writer", "Teleplay"),
                _crew(23, "Adapter", "Adaptation"),
                _crew(24, "Dialogue Writer", "Dialogue"),
            ],
        }
    )

    assert _roles_by_name(rows) == {
        ("Lead Actor", "ACTOR"),
        ("Some Director", "DIRECTOR"),
        ("Novelist", "SOURCE_AUTHOR"),
        ("Book Author", "SOURCE_AUTHOR"),
        ("Short Story Author", "SOURCE_AUTHOR"),
        ("Comic Author", "SOURCE_AUTHOR"),
        ("Graphic Novelist", "SOURCE_AUTHOR"),
        ("Playwright", "SOURCE_AUTHOR"),
        ("Character Creator", "SOURCE_AUTHOR"),
        ("Screenplay Writer", "WRITER"),
        ("Plain Writer", "WRITER"),
        ("Teleplay Writer", "WRITER"),
        ("Adapter", "WRITER"),
        ("Dialogue Writer", "WRITER"),
    }


def test_series_crew_maps_source_author_and_writer_by_job():
    """Series get the same writing crew — and no DIRECTOR from ``crew``."""
    rows = series_service.map_series_credits(
        {
            "cast": [_cast(2, "Series Lead")],
            "crew": [
                _crew(30, "Saga Novelist", "Novel"),
                _crew(31, "Series Teleplay Writer", "Teleplay"),
                # TV credits do carry per-episode directors; series-level
                # DIRECTOR is not a role of this domain (docs/schema.md).
                _crew(32, "Episode Director", "Director"),
            ],
        }
    )

    assert _roles_by_name(rows) == {
        ("Series Lead", "ACTOR"),
        ("Saga Novelist", "SOURCE_AUTHOR"),
        ("Series Teleplay Writer", "WRITER"),
    }


def test_storyboard_jobs_never_become_credits():
    """Regression: the ``Writing`` department carries animation storyboard.

    ``Story Artist`` appears in 32 of 40 sampled films. Filtering by department
    would persist illustrators as writers; filtering by job drops them.
    """
    crew = [
        _crew(40, "Storyboard Artist", "Story Artist"),
        _crew(41, "Story Boss", "Head of Story"),
        _crew(42, "Story Overseer", "Story Supervisor"),
        _crew(43, "Songwriter", "Lyricist"),
    ]

    assert movies_service.map_movie_credits({"cast": [], "crew": crew}) == []
    assert series_service.map_series_credits({"cast": [], "crew": crew}) == []


def test_story_screenstory_and_original_story_are_not_source_author():
    """In TMDB they mean 'screen story' — original material, not a prior work."""
    # The three jobs are excluded for the same reason: *Inside Out* adapts
    # nothing, yet TMDB credits Pete Docter and Ronnie del Carmen with
    # ``Original Story``, exactly as it credits screen stories with ``Story``.
    crew = [
        _crew(50, "Screen Storyteller", "Story"),
        _crew(51, "Screenstory Writer", "Screenstory"),
        _crew(52, "Inside Out Storyteller", "Original Story"),
    ]

    assert movies_service.map_movie_credits({"cast": [], "crew": crew}) == []
    assert series_service.map_series_credits({"cast": [], "crew": crew}) == []


def test_real_adaptation_splits_writer_and_source_author_across_people():
    """*The Shining*: the screenplay is Johnson/Kubrick's, the novel is King's."""
    rows = movies_service.map_movie_credits(
        {
            "cast": [],
            "crew": [
                {"id": 240, "name": "Stanley Kubrick", "job": "Director", "profile_path": None},
                _crew(240, "Stanley Kubrick", "Screenplay"),
                _crew(241, "Diane Johnson", "Screenplay"),
                _crew(242, "Stephen King", "Novel"),
            ],
        }
    )

    by_role: dict[str, set[str]] = {}
    for row in rows:
        by_role.setdefault(row.role, set()).add(row.name)

    assert by_role["SOURCE_AUTHOR"] == {"Stephen King"}
    assert by_role["WRITER"] == {"Stanley Kubrick", "Diane Johnson"}
    assert by_role["DIRECTOR"] == {"Stanley Kubrick"}
    # The author of the source work is not credited as a screenwriter, which is
    # the whole reason WRITER cannot serve as the book -> film bridge.
    assert by_role["SOURCE_AUTHOR"].isdisjoint(by_role["WRITER"])


def test_two_writing_jobs_for_one_person_yield_a_single_credit():
    """``Screenplay`` + ``Writer`` fold into one WRITER row, not a duplicate.

    ``uq_credit`` is (item_type, item_id, person_id, role): emitting the row
    twice would hand both write paths a duplicate of the same unique tuple.
    """
    rows = movies_service.map_movie_credits(
        {
            "cast": [],
            "crew": [
                _crew(60, "Busy Writer", "Screenplay"),
                _crew(60, "Busy Writer", "Writer"),
                _crew(60, "Busy Writer", "Novel"),
            ],
        }
    )

    assert sorted((row.name, row.role) for row in rows) == [
        ("Busy Writer", "SOURCE_AUTHOR"),
        ("Busy Writer", "WRITER"),
    ]


def test_empty_or_missing_crew_is_harmless():
    assert movies_service.map_movie_credits(None) == []
    assert series_service.map_series_credits(None) == []
    assert movies_service.map_movie_credits({"cast": []}) == []
    assert series_service.map_series_credits({"cast": []}) == []


# ── Write path 1: on-demand ──────────────────────────────────────────────────


async def test_on_demand_movie_persists_source_author_and_writer(db):
    """``GET /movies/{slug}`` fallback writes the new roles, one person at a time."""
    detail = {
        "id": 694,
        "title": "The Shining",
        "original_title": "The Shining",
        "release_date": "1980-05-23",
        "genres": [],
    }
    credits_payload = {
        "cast": [_cast(701, "Jack Nicholson")],
        "crew": [
            _crew(702, "Kubrick On Demand", "Director"),
            _crew(703, "Johnson On Demand", "Screenplay"),
            _crew(704, "King On Demand", "Novel"),
            _crew(705, "Storyboarder On Demand", "Story Artist"),
        ],
    }

    with (
        patch.object(
            movies_service._tmdb, "search_movie", new_callable=AsyncMock, return_value=[{"id": 694}]
        ),
        patch.object(
            movies_service._tmdb, "get_movie_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=credits_payload,
        ),
    ):
        result = await movies_service.get_movie(db, "the-shining-1980")

    persisted = await _persisted_roles(db, "MOVIE", result.id)
    assert persisted == {
        ("Jack Nicholson", "ACTOR"),
        ("Kubrick On Demand", "DIRECTOR"),
        ("Johnson On Demand", "WRITER"),
        ("King On Demand", "SOURCE_AUTHOR"),
    }
    # And the detail response carries them without any schema change.
    assert {(c.person_name, c.role) for c in result.credits} == persisted


async def test_on_demand_series_persists_source_author_and_writer(db):
    """``GET /series/{slug}`` fallback now reads ``crew``, which it ignored before."""
    detail = {
        "id": 71912,
        "name": "The Witcher",
        "original_name": "The Witcher",
        "first_air_date": "2019-12-20",
        "genres": [],
        "created_by": [{"id": 801, "name": "Witcher Showrunner", "profile_path": None}],
    }
    credits_payload = {
        "cast": [_cast(802, "Henry Cavill")],
        "crew": [
            _crew(803, "Sapkowski On Demand", "Novel"),
            _crew(804, "Teleplay On Demand", "Teleplay"),
            _crew(805, "Story Supervisor On Demand", "Story Supervisor"),
        ],
    }

    with (
        patch.object(
            series_service._tmdb,
            "search_series",
            new_callable=AsyncMock,
            return_value=[{"id": 71912}],
        ),
        patch.object(
            series_service._tmdb, "get_series_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(
            series_service._tmdb,
            "get_series_credits",
            new_callable=AsyncMock,
            return_value=credits_payload,
        ),
    ):
        result = await series_service.get_series(db, "the-witcher-2019")

    assert await _persisted_roles(db, "SERIES", result.id) == {
        ("Henry Cavill", "ACTOR"),
        ("Witcher Showrunner", "CREATOR"),
        ("Sapkowski On Demand", "SOURCE_AUTHOR"),
        ("Teleplay On Demand", "WRITER"),
    }


# ── Write path 2: seeding / backfill ─────────────────────────────────────────


async def test_seeding_payload_carries_the_writing_crew():
    """The seeding funnel maps the crew of the embedded ``credits`` sub-resource."""
    detail = {
        "id": 275,
        "title": "Fargo",
        "credits": {
            "cast": [_cast(901, "Seeded Actor")],
            "crew": [
                _crew(902, "Seeded Director", "Director"),
                _crew(903, "Seeded Novelist", "Novel"),
                _crew(904, "Seeded Screenwriter", "Screenplay"),
                _crew(905, "Seeded Storyboarder", "Head of Story"),
            ],
        },
    }

    with (
        patch.object(
            sync_jobs._tmdb_movies, "get_movie_detail", new_callable=AsyncMock, return_value=detail
        ),
        patch.object(sync_jobs._tmdb_movies, "movie_to_dict", return_value={"title": "Fargo"}),
    ):
        _item, people = await sync_jobs._fetch_movie_payload("275")

    assert _roles_by_name(people) == {
        ("Seeded Actor", "ACTOR"),
        ("Seeded Director", "DIRECTOR"),
        ("Seeded Novelist", "SOURCE_AUTHOR"),
        ("Seeded Screenwriter", "WRITER"),
    }


async def test_targeted_backfill_writes_the_new_movie_roles(db):
    """The bulk credits path (``bulk_load_credits``) persists the new roles too."""
    movie = Movie(title="Backfilled Movie", slug="backfilled-movie-74", last_synced_at=_now())
    db.add(movie)
    await db.flush()
    db.add(ExternalId(item_type="MOVIE", item_id=movie.id, source="TMDB", external_id="740001"))
    await db.flush()

    credits_payload = {
        "cast": [_cast(1001, "Backfill Actor")],
        "crew": [
            _crew(1002, "Backfill Director", "Director"),
            _crew(1003, "Backfill Novelist", "Novel"),
            _crew(1004, "Backfill Screenwriter", "Screenplay"),
            _crew(1005, "Backfill Storyboarder", "Story Artist"),
            _crew(1006, "Backfill Screen Storyteller", "Story"),
        ],
    }

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            movies_service._tmdb,
            "get_movie_credits",
            new_callable=AsyncMock,
            return_value=credits_payload,
        ),
    ):
        summary = await sync_jobs.sync_missing_credits("movie")

    assert await _persisted_roles(db, "MOVIE", movie.id) == {
        ("Backfill Actor", "ACTOR"),
        ("Backfill Director", "DIRECTOR"),
        ("Backfill Novelist", "SOURCE_AUTHOR"),
        ("Backfill Screenwriter", "WRITER"),
    }
    assert summary["credits_written"] == 4
    assert summary["people_errors"] == 0


async def test_targeted_backfill_writes_the_new_series_roles(db):
    """Same for series, whose payload arrives via ``append_to_response=credits``."""
    series = Series(title="Backfilled Series", slug="backfilled-series-74", last_synced_at=_now())
    db.add(series)
    await db.flush()
    db.add(ExternalId(item_type="SERIES", item_id=series.id, source="TMDB", external_id="740002"))
    await db.flush()

    detail = {
        "id": 740002,
        "credits": {
            "cast": [_cast(1101, "Backfill Series Actor")],
            "crew": [
                _crew(1102, "Backfill Saga Author", "Comic Book"),
                _crew(1103, "Backfill Dialogue Writer", "Dialogue"),
                _crew(1104, "Backfill Story Boss", "Head of Story"),
            ],
        },
        "created_by": [{"id": 1105, "name": "Backfill Creator", "profile_path": None}],
    }

    with (
        patch("backlogg.scheduler.jobs.async_session_factory", new=_session_factory(db)),
        patch.object(
            sync_jobs._tmdb_series,
            "get_series_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ),
    ):
        summary = await sync_jobs.sync_missing_credits("series")

    assert await _persisted_roles(db, "SERIES", series.id) == {
        ("Backfill Series Actor", "ACTOR"),
        ("Backfill Creator", "CREATOR"),
        ("Backfill Saga Author", "SOURCE_AUTHOR"),
        ("Backfill Dialogue Writer", "WRITER"),
    }
    assert summary["credits_written"] == 4


# ── The cross-type authorship query ──────────────────────────────────────────


async def _person(db, name: str, slug: str) -> Person:
    person = Person(name=name, slug=slug, last_synced_at=_now())
    db.add(person)
    await db.flush()
    return person


async def _credit(db, item_type: str, item_id: int, person: Person, role: str) -> None:
    db.add(Credit(item_type=item_type, item_id=item_id, person_id=person.id, role=role))
    await db.flush()


async def test_authorship_links_a_person_works_in_both_directions(db):
    """King's novel and its film adaptation reach each other through the person."""
    king = await _person(db, "Cross King", "cross-king-74")

    book = Book(title="Cross Shining", slug="cross-shining-74", last_synced_at=_now())
    movie = Movie(title="Cross Shining Film", slug="cross-shining-film-74", last_synced_at=_now())
    series = Series(title="Cross Shining TV", slug="cross-shining-tv-74", last_synced_at=_now())
    db.add_all([book, movie, series])
    await db.flush()

    await _credit(db, "BOOK", book.id, king, "AUTHOR")
    await _credit(db, "MOVIE", movie.id, king, "SOURCE_AUTHOR")
    await _credit(db, "SERIES", series.id, king, "SOURCE_AUTHOR")

    works = await recs_repo.get_authorship_works(db, king.id)
    assert {(row.item_type, row.item_id) for row in works} == {
        ("BOOK", book.id),
        ("MOVIE", movie.id),
        ("SERIES", series.id),
    }
    assert {row.slug for row in works} == {
        "cross-shining-74",
        "cross-shining-film-74",
        "cross-shining-tv-74",
    }

    # Book -> screen…
    from_book = await recs_repo.get_authorship_works(db, king.id, exclude=("BOOK", book.id))
    assert ("MOVIE", movie.id) in {(row.item_type, row.item_id) for row in from_book}
    assert ("BOOK", book.id) not in {(row.item_type, row.item_id) for row in from_book}

    # …and screen -> book.
    from_movie = await recs_repo.get_authorship_works(db, king.id, exclude=("MOVIE", movie.id))
    assert ("BOOK", book.id) in {(row.item_type, row.item_id) for row in from_movie}
    assert ("MOVIE", movie.id) not in {(row.item_type, row.item_id) for row in from_movie}


async def test_translator_credited_as_book_is_not_linked(db):
    """A ``job: "Book"`` translator has no book of their own — no bridge."""
    translator = await _person(db, "Cross Translator", "cross-translator-74")

    movie = Movie(title="Cross Witcher Film", slug="cross-witcher-film-74", last_synced_at=_now())
    db.add(movie)
    await db.flush()
    await _credit(db, "MOVIE", movie.id, translator, "SOURCE_AUTHOR")

    assert await recs_repo.get_authorship_works(db, translator.id) == []


async def test_author_credit_on_a_book_outside_the_catalog_does_not_open_the_gate(db):
    """The gate joins ``books``: a dangling BOOK credit is not a catalog book.

    ``credits`` has no real FK (docs/conventions.md), so the row alone proves
    nothing.
    """
    ghost = await _person(db, "Cross Ghost Author", "cross-ghost-author-74")

    movie = Movie(title="Cross Ghost Film", slug="cross-ghost-film-74", last_synced_at=_now())
    db.add(movie)
    await db.flush()
    await _credit(db, "BOOK", 999_000_074, ghost, "AUTHOR")
    await _credit(db, "MOVIE", movie.id, ghost, "SOURCE_AUTHOR")

    assert await recs_repo.get_authorship_works(db, ghost.id) == []


async def test_writer_and_other_roles_are_not_authorship(db):
    """WRITER/DIRECTOR/ACTOR carry zero authorship weight — they never show up."""
    author = await _person(db, "Cross Screenwriter Author", "cross-screenwriter-author-74")

    book = Book(title="Cross Only Book", slug="cross-only-book-74", last_synced_at=_now())
    movie = Movie(title="Cross Scripted Film", slug="cross-scripted-film-74", last_synced_at=_now())
    db.add_all([book, movie])
    await db.flush()

    await _credit(db, "BOOK", book.id, author, "AUTHOR")
    await _credit(db, "MOVIE", movie.id, author, "WRITER")
    await _credit(db, "MOVIE", movie.id, author, "DIRECTOR")

    works = await recs_repo.get_authorship_works(db, author.id)
    assert [(row.item_type, row.item_id) for row in works] == [("BOOK", book.id)]


async def test_authorship_query_ignores_other_peoples_credits(db):
    """A person with no authorship credit at all gets an empty list."""
    nobody = await _person(db, "Cross Nobody", "cross-nobody-74")
    assert await recs_repo.get_authorship_works(db, nobody.id) == []
