"""Feature 92 — ``GET /v1/{type}/{slug}/adaptations`` on the four content types.

What is under test, and why each of these is worth a test:

- the endpoint exists on the four routers with **one** contract, because the
  frontend section that consumes it (FE-66) is one component rendered on four
  detail pages;
- every entry carries the related item's ``item_type``, which is the field this
  project has already got wrong three times (issues #32, #33, #36) and the one
  the caller cannot infer — the related item may be of **any** of the four
  types, including the same one as the item in the URL;
- **same-type edges are served, not filtered** (``progress/current.md`` §2.3
  bis). ``P144`` asserts a derivation, not a change of medium, so a remake or a
  spin-off series of another series is a legitimate edge, and it is the
  majority of the real data: 16 of the 18 edges in the development catalog are
  ``SERIES``→``SERIES``. Two things could silently regress it — a filter by
  type, or resolving the direction from the type instead of the id — and both
  would take almost everything FE-66 renders with them;
- the **direction** is in the data. The same stored edge reads as "this comes
  from that" or "that came out of this" depending on which end you are
  standing on, and only one of the two rows is stored (feature 79 does not
  write the mirror), so both sides are asserted explicitly;
- an item with no adaptations answers ``200`` with an empty list. That is the
  normal case for most of the catalog, and a 404 there would make the frontend
  hide the item rather than the section;
- ``source='INTERNAL'`` rows — the co-occurrence layer feature 83 will write
  into the very same table — do not appear.
"""

from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.games import repository as games_repo
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.series import repository as series_repo
from backlogg.shared.item_relations import (
    RELATION_ADAPTATION,
    RELATION_COOCCURRENCE,
    RELATION_DERIVATIVE,
    SOURCE_INTERNAL,
    SOURCE_WIKIDATA,
    RelationWrite,
    upsert_item_relations,
)

pytestmark = pytest.mark.asyncio


def _movie_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": date(2000, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
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
    }


def _series_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "first_air_date": date(2001, 1, 1),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "overview",
        "first_publish_date": date(1965, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_data(slug: str, title: str) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": date(1992, 1, 1),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _edge(db, from_type, from_id, to_type, to_id, relation, source=SOURCE_WIKIDATA):
    await upsert_item_relations(
        db,
        [
            RelationWrite(
                from_type=from_type,
                from_id=from_id,
                to_type=to_type,
                to_id=to_id,
                relation=relation,
                source=source,
            )
        ],
    )


# ── The four types answer, with the same contract ─────────────────────────────


async def test_all_four_types_expose_adaptations_with_the_same_contract(client, db):
    """One novel adapted into a film, a series and a game: four pages, one shape.

    The fixture is deliberately a star around the book, because that is the
    only arrangement where the same edge has to be read from a movie page, a
    series page, a game page and the book's own page.
    """
    book = await books_repo.upsert_book(db, _book_data("ad-contract-book", "Contract Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-contract-movie", "Contract Film"))
    series = await series_repo.upsert_series(
        db, _series_data("ad-contract-series", "Contract Series")
    )
    game = await games_repo.upsert_game(db, _game_data("ad-contract-game", "Contract Game"))

    # film/series are *based on* the novel; the game is *derived from* it.
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "SERIES", series.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "BOOK", book.id, "GAME", game.id, RELATION_DERIVATIVE)

    expected_keys = {"item_type", "slug", "title", "poster_url", "direction"}

    for path, expected in [
        ("/v1/movies/ad-contract-movie/adaptations", [("BOOK", "ad-contract-book", "SOURCE")]),
        ("/v1/series/ad-contract-series/adaptations", [("BOOK", "ad-contract-book", "SOURCE")]),
        ("/v1/games/ad-contract-game/adaptations", [("BOOK", "ad-contract-book", "SOURCE")]),
    ]:
        response = await client.get(path)
        assert response.status_code == 200, path
        results = response.json()["results"]
        assert [(r["item_type"], r["slug"], r["direction"]) for r in results] == expected, path
        assert set(results[0].keys()) == expected_keys, path

    response = await client.get("/v1/books/ad-contract-book/adaptations")
    assert response.status_code == 200
    results = response.json()["results"]
    assert {(r["item_type"], r["slug"], r["direction"]) for r in results} == {
        ("MOVIE", "ad-contract-movie", "DERIVED"),
        ("SERIES", "ad-contract-series", "DERIVED"),
        ("GAME", "ad-contract-game", "DERIVED"),
    }
    for entry in results:
        assert set(entry.keys()) == expected_keys


async def test_entry_carries_title_and_poster_url_of_the_related_item(client, db):
    """The payload describes the *other* item, not the one in the URL."""
    book = await books_repo.upsert_book(db, _book_data("ad-fields-book", "Fields Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-fields-movie", "Fields Film"))
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)

    entry = (await client.get("/v1/movies/ad-fields-movie/adaptations")).json()["results"][0]
    assert entry["title"] == "Fields Novel"
    assert entry["item_type"] == "BOOK"
    assert entry["slug"] == "ad-fields-book"
    # The book fixture has no cover and the film does — so a payload echoing
    # the anchor's poster instead of the neighbour's would be visible here.
    assert entry["poster_url"] is None

    entry = (await client.get("/v1/books/ad-fields-book/adaptations")).json()["results"][0]
    assert entry["title"] == "Fields Film"
    assert entry["item_type"] == "MOVIE"
    assert entry["poster_url"] == "https://example.com/ad-fields-movie.jpg"


# ── The two directions ────────────────────────────────────────────────────────


async def test_the_same_edge_reads_as_source_from_one_end_and_derived_from_the_other(client, db):
    """One stored ``ADAPTATION`` row, two opposite readings.

    ``item_relations`` holds the film→novel row only; the novel→film mirror is
    never written (feature 79). If the direction were taken from the relation
    alone, both pages would claim the same thing.
    """
    book = await books_repo.upsert_book(db, _book_data("ad-dir-book", "Direction Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-dir-movie", "Direction Film"))
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)

    from_movie = (await client.get("/v1/movies/ad-dir-movie/adaptations")).json()["results"]
    assert from_movie == [
        {
            "item_type": "BOOK",
            "slug": "ad-dir-book",
            "title": "Direction Novel",
            "poster_url": None,
            "direction": "SOURCE",
        }
    ]

    from_book = (await client.get("/v1/books/ad-dir-book/adaptations")).json()["results"]
    assert from_book == [
        {
            "item_type": "MOVIE",
            "slug": "ad-dir-movie",
            "title": "Direction Film",
            "poster_url": "https://example.com/ad-dir-movie.jpg",
            "direction": "DERIVED",
        }
    ]


async def test_derivative_edges_read_inversely_to_adaptation_edges(client, db):
    """``DERIVATIVE`` points the other way round than ``ADAPTATION``.

    ``P4969`` stores "*to* is derived from *from*", so the ``from`` end is the
    origin — the opposite of ``P144``. Getting the two confused would flip the
    text on every page that uses it, which is why both are pinned.
    """
    book = await books_repo.upsert_book(db, _book_data("ad-deriv-book", "Derivative Novel"))
    game = await games_repo.upsert_game(db, _game_data("ad-deriv-game", "Derivative Game"))
    await _edge(db, "BOOK", book.id, "GAME", game.id, RELATION_DERIVATIVE)

    from_book = (await client.get("/v1/books/ad-deriv-book/adaptations")).json()["results"]
    assert [(r["item_type"], r["direction"]) for r in from_book] == [("GAME", "DERIVED")]

    from_game = (await client.get("/v1/games/ad-deriv-game/adaptations")).json()["results"]
    assert [(r["item_type"], r["direction"]) for r in from_game] == [("BOOK", "SOURCE")]


async def test_both_directions_can_coexist_in_one_response(client, db):
    """A film based on a novel that also spun off a game: one list, two labels."""
    book = await books_repo.upsert_book(db, _book_data("ad-both-book", "Both Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-both-movie", "Both Film"))
    game = await games_repo.upsert_game(db, _game_data("ad-both-game", "Both Game"))
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "MOVIE", movie.id, "GAME", game.id, RELATION_DERIVATIVE)

    results = (await client.get("/v1/movies/ad-both-movie/adaptations")).json()["results"]
    assert {(r["slug"], r["direction"]) for r in results} == {
        ("ad-both-book", "SOURCE"),
        ("ad-both-game", "DERIVED"),
    }


# ── Same-type edges: the majority case in the real data ───────────────────────


async def test_same_type_edge_is_served_and_reads_correctly_from_both_ends(client, db):
    """Two ``SERIES``: one based on the other. Served, and with the right ends.

    This is what 16 of the 18 real edges look like (*Batman: The Animated
    Series* → *The New Batman Adventures*), and the decision to serve them
    rather than filter them is written down in ``progress/current.md`` §2.3
    bis: ``P144`` asserts a derivation, not a change of medium.

    Two distinct regressions die here, and neither is caught anywhere else in
    this file:

    1. a filter by content type — it would empty out almost every real
       response while every other test in this file still passed;
    2. resolving the direction from ``from_type``/``to_type`` instead of from
       the **id**. With both ends of the same type, ``edge.from_type ==
       item_type`` is true on *both* pages, so a type-based check would report
       ``SOURCE`` from both ends and, worse, return the anchor itself as its
       own adaptation.
    """
    older = await series_repo.upsert_series(db, _series_data("ad-same-older", "Same Older"))
    newer = await series_repo.upsert_series(db, _series_data("ad-same-newer", "Same Newer"))
    # ADAPTATION: *from* is based on *to* — the newer series is based on the older.
    await _edge(db, "SERIES", newer.id, "SERIES", older.id, RELATION_ADAPTATION)

    from_newer = (await client.get("/v1/series/ad-same-newer/adaptations")).json()["results"]
    assert from_newer == [
        {
            "item_type": "SERIES",
            "slug": "ad-same-older",
            "title": "Same Older",
            "poster_url": "https://example.com/ad-same-older.jpg",
            "direction": "SOURCE",
        }
    ]

    from_older = (await client.get("/v1/series/ad-same-older/adaptations")).json()["results"]
    assert from_older == [
        {
            "item_type": "SERIES",
            "slug": "ad-same-newer",
            "title": "Same Newer",
            "poster_url": "https://example.com/ad-same-newer.jpg",
            "direction": "DERIVED",
        }
    ]

    # Neither page lists itself: the far end is picked by id, not by type.
    assert "ad-same-newer" not in {r["slug"] for r in from_newer}
    assert "ad-same-older" not in {r["slug"] for r in from_older}


async def test_same_type_and_cross_type_edges_coexist_in_one_response(client, db):
    """A series based on a novel *and* on an earlier series: both come back."""
    book = await books_repo.upsert_book(db, _book_data("ad-mix-book", "Mix Novel"))
    origin = await series_repo.upsert_series(db, _series_data("ad-mix-origin", "Mix Origin"))
    series = await series_repo.upsert_series(db, _series_data("ad-mix-series", "Mix Series"))
    await _edge(db, "SERIES", series.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "SERIES", series.id, "SERIES", origin.id, RELATION_ADAPTATION)

    results = (await client.get("/v1/series/ad-mix-series/adaptations")).json()["results"]
    assert {(r["item_type"], r["slug"], r["direction"]) for r in results} == {
        ("BOOK", "ad-mix-book", "SOURCE"),
        ("SERIES", "ad-mix-origin", "SOURCE"),
    }


async def test_inverse_statements_about_the_same_pair_collapse_to_one_entry(client, db):
    """``P144`` and ``P4969`` are inverses, so a curated pair arrives twice.

    Both rows are stored (the unique key carries ``relation``), and both say
    the same thing from opposite ends. The response shows the neighbour once.
    """
    book = await books_repo.upsert_book(db, _book_data("ad-dedup-book", "Dedup Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-dedup-movie", "Dedup Film"))
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "BOOK", book.id, "MOVIE", movie.id, RELATION_DERIVATIVE)

    results = (await client.get("/v1/movies/ad-dedup-movie/adaptations")).json()["results"]
    assert len(results) == 1
    assert (results[0]["slug"], results[0]["direction"]) == ("ad-dedup-book", "SOURCE")


# ── Empty vs. missing ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("prefix", "maker", "repo_call"),
    [
        ("movies", _movie_data, "movie"),
        ("series", _series_data, "series"),
        ("books", _book_data, "book"),
        ("games", _game_data, "game"),
    ],
)
async def test_item_without_adaptations_returns_200_and_an_empty_list(
    client, db, prefix, maker, repo_call
):
    """The common case: most of the catalog has no adaptation at all."""
    upsert = {
        "movie": movies_repo.upsert_movie,
        "series": series_repo.upsert_series,
        "book": books_repo.upsert_book,
        "game": games_repo.upsert_game,
    }[repo_call]
    slug = f"ad-empty-{repo_call}"
    await upsert(db, maker(slug, f"Empty {repo_call}"))

    response = await client.get(f"/v1/{prefix}/{slug}/adaptations")
    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize(
    ("prefix", "detail"),
    [
        ("movies", "Movie not found"),
        ("series", "Series not found"),
        ("books", "Book not found"),
        ("games", "Game not found"),
    ],
)
async def test_unknown_slug_returns_404(client, prefix, detail):
    """404 is reserved for the slug that names nothing."""
    response = await client.get(f"/v1/{prefix}/ad-no-such-slug/adaptations")
    assert response.status_code == 404
    assert response.json()["detail"] == detail


# ── Only the Wikidata layer ───────────────────────────────────────────────────


async def test_internal_cooccurrence_edges_are_not_returned(client, db):
    """Feature 83 shares the table; its layer stays out of this response."""
    book = await books_repo.upsert_book(db, _book_data("ad-source-book", "Source Novel"))
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-source-movie", "Source Film"))
    neighbour = await movies_repo.upsert_movie(
        db, _movie_data("ad-source-neighbour", "Neighbour Film")
    )
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(
        db,
        "MOVIE",
        movie.id,
        "MOVIE",
        neighbour.id,
        RELATION_COOCCURRENCE,
        source=SOURCE_INTERNAL,
    )
    # Same pair, same relation, other provenance: only the source tells them
    # apart, so a filter that forgot it would leak this one too.
    await _edge(
        db, "MOVIE", movie.id, "MOVIE", neighbour.id, RELATION_ADAPTATION, source=SOURCE_INTERNAL
    )

    results = (await client.get("/v1/movies/ad-source-movie/adaptations")).json()["results"]
    assert [r["slug"] for r in results] == ["ad-source-book"]


async def test_edge_pointing_at_a_missing_item_is_dropped_not_served_broken(client, db):
    """``item_relations`` has no FKs, so an end can be gone.

    The alternative to dropping it is an entry whose link is guaranteed to
    404 — exactly the silent broken link this feature is meant to avoid.
    """
    movie = await movies_repo.upsert_movie(db, _movie_data("ad-dangling-movie", "Dangling Film"))
    book = await books_repo.upsert_book(db, _book_data("ad-dangling-book", "Dangling Novel"))
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id, RELATION_ADAPTATION)
    await _edge(db, "MOVIE", movie.id, "BOOK", book.id + 10_000_000, RELATION_ADAPTATION)

    results = (await client.get("/v1/movies/ad-dangling-movie/adaptations")).json()["results"]
    assert [r["slug"] for r in results] == ["ad-dangling-book"]
