"""Feature 80 — ``/similar`` over the HNSW index, on the four content types.

The rules of the ranker are proved in ``test_similar_ranking.py``, against pure
functions.  What is proved *here* is everything that only exists once the
database is involved:

- the **four** endpoints answer from the vector index, with no call to TMDB,
  Open Library or IGDB.  The adapters are replaced by explosives: if the
  semantic path silently stopped working, the fallback would quietly serve the
  old answer and a test that only looked at the payload would still pass;
- every result carries its own ``item_type``.  Before this feature the type was
  implicit — whatever page you were on — and ``apps/web`` still builds links as
  ``/{type-of-the-page}/{slug}``.  A book among films with no ``item_type`` is
  issues #32/#33/#36 all over again;
- ``reason`` arrives as **structured data**, never as a formed sentence.  FE-69
  renders it in Spanish and English, and an English phrase assembled here is
  untranslatable on arrival;
- the **anchor never appears in its own results**.  Cosine with itself is
  exactly 1.0, so it is the top result of every query that does not exclude it;
- an item **outside the embedded subset** falls back to the path it has always
  used.  ``EMBEDDING_MAX_ITEMS`` caps the subset at 40.000, so in production
  most of the catalog lands there, and "the rewrite emptied the carousel for
  60% of the catalog" is the regression this feature most easily causes;
- the quota and the diversification penalty, which are env-configured, do what
  the pure tests say **through the endpoint** — including the fact that the
  merged default (``SIMILAR_CROSS_TYPE_QUOTA=0``) returns no cross-type result
  at all when the same-type neighbours are closer.
"""

import math
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.books import service as books_service
from backlogg.core.config import settings
from backlogg.games import repository as games_repo
from backlogg.games import service as games_service
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.movies import service as movies_service
from backlogg.series import repository as series_repo
from backlogg.series import service as series_service
from backlogg.shared.item_embeddings import EmbeddingWrite, upsert_item_embeddings

pytestmark = pytest.mark.asyncio

DIM = settings.EMBEDDING_DIM
MODEL = "f80-test-model"


# ── Vectors with predictable cosines ──────────────────────────────────────────


def _axis(index: int) -> list[float]:
    vector = [0.0] * DIM
    vector[index] = 1.0
    return vector


def _blend(near: int, far: int, weight: float) -> list[float]:
    """Unit vector whose cosine against ``_axis(near)`` is exactly ``weight``."""
    vector = [0.0] * DIM
    vector[near] = weight
    vector[far] = math.sqrt(max(0.0, 1.0 - weight * weight))
    return vector


async def _embed(db, item_type: str, item_id: int, vector: list[float]) -> None:
    await upsert_item_embeddings(
        db,
        [
            EmbeddingWrite(
                item_type=item_type,
                item_id=item_id,
                embedding=vector,
                model=MODEL,
                source_hash=f"{item_type}-{item_id}",
            )
        ],
    )


# ── Catalog fixtures ──────────────────────────────────────────────────────────


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
        "rating_external": 7.0,
        "rating_count_external": 10,
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
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book_data(slug: str, title: str, genres: list[dict] | None = None) -> dict:
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
        "genres": genres or [],
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
        "poster_url": None,
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


@pytest.fixture
def no_external_calls():
    """Every external similar-items adapter, replaced by an explosive.

    The semantic path is supposed to make **no external call at all**. Asserting
    that by inspecting the payload would not work: the fallback returns the same
    shape, so a broken vector path would look like a passing test.
    """
    boom = AsyncMock(side_effect=AssertionError("the semantic path called an external API"))
    with (
        patch.object(movies_service._tmdb, "get_movie_recommendations", boom),
        patch.object(series_service._tmdb, "get_series_recommendations", boom),
        patch.object(games_service._igdb_client, "get_game_by_slug", boom),
    ):
        yield


@pytest_asyncio.fixture
async def star(db):
    """One item of each type, all embedded, all near the movie at axis 0.

    A star and not a chain: it is the only arrangement where the neighbours of
    *every* type include the other three, so the same fixture answers the
    cross-type question from four different pages.
    """
    movie = await movies_repo.upsert_movie(db, _movie_data("f80-star-movie", "Star Film"))
    book = await books_repo.upsert_book(db, _book_data("f80-star-book", "Star Novel"))
    series = await series_repo.upsert_series(db, _series_data("f80-star-series", "Star Series"))
    game = await games_repo.upsert_game(db, _game_data("f80-star-game", "Star Game"))

    await _embed(db, "MOVIE", movie.id, _axis(0))
    await _embed(db, "BOOK", book.id, _blend(0, 1, 0.95))
    await _embed(db, "SERIES", series.id, _blend(0, 2, 0.90))
    await _embed(db, "GAME", game.id, _blend(0, 3, 0.85))
    return {"MOVIE": movie, "BOOK": book, "SERIES": series, "GAME": game}


# ── The four types answer from the index, without calling anyone ──────────────


async def test_four_types_serve_similar_from_the_vector_index(
    db, star, no_external_calls, monkeypatch
):
    """Each page returns the other three items, each labelled with its own type.

    Runs with the quota **on**, because that is what cross-type means now: at
    the merged default of 0 the index query is narrowed to the anchor's own
    type and this fixture — one item per type — correctly answers empty.
    """
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)
    expected_by_anchor = {
        "movies": ("f80-star-movie", "MOVIE"),
        "series": ("f80-star-series", "SERIES"),
        "books": ("f80-star-book", "BOOK"),
        "games": ("f80-star-game", "GAME"),
    }
    callers = {
        "movies": movies_service.get_similar_movies,
        "series": series_service.get_similar_series,
        "books": books_service.get_similar_books,
        "games": games_service.get_similar_games,
    }
    for path, (slug, anchor_type) in expected_by_anchor.items():
        out = await callers[path](db, slug)
        by_type = {r.item_type: r for r in out.results}
        assert len(out.results) == 3, path
        assert set(by_type) == {"MOVIE", "SERIES", "BOOK", "GAME"} - {anchor_type}, path
        for result in out.results:
            assert result.reason.kind == "SEMANTIC_CROSS_TYPE"
            assert result.reason.source is None
            assert 0.0 < result.reason.score <= 1.0


async def test_results_are_ordered_by_cosine_similarity(db, star, no_external_calls, monkeypatch):
    """The novel (0.95) before the series (0.90) before the game (0.85)."""
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)
    out = await movies_service.get_similar_movies(db, "f80-star-movie")
    assert [r.slug for r in out.results] == [
        "f80-star-book",
        "f80-star-series",
        "f80-star-game",
    ]
    assert [r.reason.score for r in out.results] == sorted(
        (r.reason.score for r in out.results), reverse=True
    )


async def test_endpoint_payload_carries_item_type_and_a_structured_reason(
    client, crowded, no_external_calls, monkeypatch
):
    """Over HTTP: the contract FE-67 and FE-69 consume, on both sides of the knob.

    ``reason`` is an object with an enumerated ``kind``, not a sentence. A
    string here would be untranslatable by the time it reached next-intl.

    The same request is made twice — at the merged default and with the quota
    on — because the payload has to be identical in shape either way: FE-67
    flips one env var and must not meet a different contract on the other side.
    """
    expected_keys = {
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
        "rating_internal",
        "reason",
    }

    response = await client.get("/v1/movies/f80-quota-anchor/similar")
    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    for entry in results:
        assert set(entry) == expected_keys
        # The merged default: the type of every row is the type of the page.
        assert entry["item_type"] == "MOVIE"
        assert isinstance(entry["reason"], dict)
        assert set(entry["reason"]) == {"kind", "score", "source"}
        assert entry["reason"]["kind"] == "SEMANTIC"
        assert entry["reason"]["source"] is None
        assert 0.0 < entry["reason"]["score"] <= 1.0

    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)
    results = (await client.get("/v1/movies/f80-quota-anchor/similar")).json()["results"]
    cross = [e for e in results if e["item_type"] != "MOVIE"]
    assert cross
    for entry in results:
        assert set(entry) == expected_keys
        assert entry["item_type"] in {"MOVIE", "SERIES", "BOOK", "GAME"}
        assert set(entry["reason"]) == {"kind", "score", "source"}
    assert all(e["reason"]["kind"] == "SEMANTIC_CROSS_TYPE" for e in cross)


# ── The anchor is never its own recommendation ────────────────────────────────


async def test_source_item_never_appears_in_its_own_results(db, no_external_calls):
    """Cosine with itself is 1.0, so it wins every query that does not exclude it."""
    anchor = await movies_repo.upsert_movie(db, _movie_data("f80-self-anchor", "Self Anchor"))
    other = await movies_repo.upsert_movie(db, _movie_data("f80-self-other", "Self Other"))
    await _embed(db, "MOVIE", anchor.id, _axis(0))
    await _embed(db, "MOVIE", other.id, _blend(0, 1, 0.99))

    out = await movies_service.get_similar_movies(db, "f80-self-anchor")

    assert [r.slug for r in out.results] == ["f80-self-other"]


async def test_a_vector_whose_item_no_longer_exists_is_dropped(db, no_external_calls):
    """``item_embeddings`` has no foreign keys — a vector can outlive its row.

    Returning it would be a link guaranteed to 404, which is the failure this
    whole feature is trying not to reintroduce.
    """
    anchor = await movies_repo.upsert_movie(db, _movie_data("f80-orphan-anchor", "Orphan Anchor"))
    other = await movies_repo.upsert_movie(db, _movie_data("f80-orphan-other", "Orphan Other"))
    await _embed(db, "MOVIE", anchor.id, _axis(0))
    await _embed(db, "MOVIE", other.id, _blend(0, 1, 0.80))
    # A vector for an item id that is not in the catalog at all.
    await _embed(db, "MOVIE", 9_999_777, _blend(0, 1, 0.99))

    out = await movies_service.get_similar_movies(db, "f80-orphan-anchor")

    assert [r.slug for r in out.results] == ["f80-orphan-other"]


# ── Cross-type quota, through the endpoint ────────────────────────────────────


@pytest_asyncio.fixture
async def crowded(db):
    """Twelve films closer than any book — what cosine returns in real life.

    Items of one type share vocabulary, so the anchor's own type sweeps the top
    of the list. Without a reserved quota the cross-media bridge never reaches
    the user; this fixture is that situation, reproduced deterministically.
    """
    anchor = await movies_repo.upsert_movie(db, _movie_data("f80-quota-anchor", "Quota Anchor"))
    await _embed(db, "MOVIE", anchor.id, _axis(0))
    names = [
        "Alpha",
        "Beta",
        "Gamma",
        "Delta",
        "Epsilon",
        "Zeta",
        "Eta",
        "Theta",
        "Iota",
        "Kappa",
        "Lambda",
        "Omega",
    ]
    for index, name in enumerate(names):
        movie = await movies_repo.upsert_movie(
            db, _movie_data(f"f80-quota-movie-{name.lower()}", f"Quota Film {name}")
        )
        await _embed(db, "MOVIE", movie.id, _blend(0, index + 1, 0.99 - index * 0.01))
    for index, name in enumerate(("One", "Two", "Three")):
        book = await books_repo.upsert_book(
            db, _book_data(f"f80-quota-book-{name.lower()}", f"Quota Novel {name}")
        )
        await _embed(db, "BOOK", book.id, _blend(0, 20 + index, 0.50 - index * 0.01))
    return anchor


async def test_quota_zero_serves_same_type_neighbours_and_hides_nearer_others(
    db, star, no_external_calls
):
    """A film with one film neighbour: served, while the nearer book is not."""
    assert settings.SIMILAR_CROSS_TYPE_QUOTA == 0
    sibling = await movies_repo.upsert_movie(db, _movie_data("f80-star-movie-2", "Star Film II"))
    # Further from the anchor than the book (0.95) and the series (0.90).
    await _embed(db, "MOVIE", sibling.id, _blend(0, 4, 0.60))

    out = await movies_service.get_similar_movies(db, "f80-star-movie")

    assert [r.slug for r in out.results] == ["f80-star-movie-2"]
    assert out.results[0].reason.kind == "SEMANTIC"


async def test_quota_on_restores_the_nearer_cross_type_neighbours(
    db, star, no_external_calls, monkeypatch
):
    """The other half of the switch: at 3, the same anchor serves them again.

    Together with the two tests above this pins both directions of the meaning
    of the knob, on one fixture: 0 → never, >0 → reserved slots.
    """
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)

    out = await movies_service.get_similar_movies(db, "f80-star-movie")

    assert {r.item_type for r in out.results} == {"BOOK", "SERIES", "GAME"}
    assert out.results[0].slug == "f80-star-book"
    assert all(r.reason.kind == "SEMANTIC_CROSS_TYPE" for r in out.results)


async def test_quota_zero_never_returns_another_type_on_the_crowded_fixture(
    db, crowded, no_external_calls, monkeypatch
):
    """The full-page version: ten same-type rows, zero of any other type."""
    assert settings.SIMILAR_CROSS_TYPE_QUOTA == 0
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.0)

    out = await movies_service.get_similar_movies(db, "f80-quota-anchor")

    assert len(out.results) == 10
    assert {r.item_type for r in out.results} == {"MOVIE"}
    assert all(r.reason.kind == "SEMANTIC" for r in out.results)


async def test_cross_type_quota_reserves_slots_when_configured(
    db, crowded, no_external_calls, monkeypatch
):
    """Turned on by env — the value the ficha asks for is 3 of 10."""
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.0)

    out = await movies_service.get_similar_movies(db, "f80-quota-anchor")

    assert len(out.results) == 10
    cross = [r for r in out.results if r.item_type != "MOVIE"]
    assert len(cross) == 3
    assert [r.slug for r in cross] == [
        "f80-quota-book-one",
        "f80-quota-book-two",
        "f80-quota-book-three",
    ]
    assert all(r.reason.kind == "SEMANTIC_CROSS_TYPE" for r in cross)


async def test_quota_is_clamped_instead_of_raising(db, crowded, no_external_calls, monkeypatch):
    """A quota above the page size saturates the page; the API does not fail."""
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 99)
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.0)

    out = await movies_service.get_similar_movies(db, "f80-quota-anchor")

    assert len(out.results) == 10
    assert sum(1 for r in out.results if r.item_type == "BOOK") == 3


# ── Diversification, through the endpoint ─────────────────────────────────────


async def test_repeated_franchise_is_demoted(db, no_external_calls, monkeypatch):
    """Five entries of one saga do not take the whole page."""
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 0)
    anchor = await movies_repo.upsert_movie(db, _movie_data("f80-div-anchor", "Div Anchor"))
    await _embed(db, "MOVIE", anchor.id, _axis(0))
    for index in range(5):
        movie = await movies_repo.upsert_movie(
            db,
            _movie_data(f"f80-div-saga-{index}", f"Saga Aurora: Chapter {index}"),
        )
        await _embed(db, "MOVIE", movie.id, _blend(0, index + 1, 0.99 - index * 0.01))
    for slug, title, weight in (
        ("f80-div-other-a", "Arrival", 0.90),
        ("f80-div-other-b", "Stalker", 0.89),
    ):
        movie = await movies_repo.upsert_movie(db, _movie_data(slug, title))
        await _embed(db, "MOVIE", movie.id, _blend(0, 10 + int(weight * 100), weight))

    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.25)
    diversified = [
        r.slug for r in (await movies_service.get_similar_movies(db, "f80-div-anchor")).results
    ]
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.0)
    raw = [r.slug for r in (await movies_service.get_similar_movies(db, "f80-div-anchor")).results]

    # The control: without the penalty the saga sweeps the top five.
    assert raw[:5] == [f"f80-div-saga-{i}" for i in range(5)]
    # With it, the saga keeps the slot it earned and yields the next two.
    assert diversified[0] == "f80-div-saga-0"
    assert set(diversified[1:3]) == {"f80-div-other-a", "f80-div-other-b"}
    # Demoted, never dropped: the page still carries everything it did before.
    assert sorted(diversified) == sorted(raw)


async def test_repeated_author_is_demoted(db, no_external_calls, monkeypatch):
    """The other half of the signal: same creator, unrelated titles."""
    from backlogg.people import repository as people_repo

    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 0)
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.25)

    author = await people_repo.upsert_person(
        db,
        {
            "name": "F80 Prolific Author",
            "slug": "f80-prolific-author",
            "profile_url": None,
            "last_synced_at": datetime.now(UTC),
        },
    )
    anchor = await books_repo.upsert_book(db, _book_data("f80-auth-anchor", "Auth Anchor"))
    await _embed(db, "BOOK", anchor.id, _axis(0))
    for index, (slug, title, weight) in enumerate(
        (
            ("f80-auth-same-1", "Nostromo", 0.99),
            ("f80-auth-same-2", "Victory", 0.98),
            ("f80-auth-other", "Pale Fire", 0.80),
        )
    ):
        book = await books_repo.upsert_book(db, _book_data(slug, title))
        await _embed(db, "BOOK", book.id, _blend(0, index + 1, weight))
        if slug.startswith("f80-auth-same"):
            await people_repo.upsert_credit(
                db,
                {
                    "item_type": "BOOK",
                    "item_id": book.id,
                    "person_id": author.id,
                    "role": "AUTHOR",
                },
            )

    out = await books_service.get_similar_books(db, "f80-auth-anchor")

    assert [r.slug for r in out.results] == [
        "f80-auth-same-1",
        "f80-auth-other",
        "f80-auth-same-2",
    ]


# ── No embedding: the fallback path, unchanged ────────────────────────────────


async def test_movie_without_embedding_falls_back_to_tmdb(db):
    """~60% of the production catalog is outside the subset. Zero regression.

    The vector table is *not* empty here — another movie is embedded — so this
    also covers the failure mode where "the layer exists" is mistaken for "this
    item is in it".
    """
    embedded = await movies_repo.upsert_movie(db, _movie_data("f80-fb-embedded", "FB Embedded"))
    await _embed(db, "MOVIE", embedded.id, _axis(0))
    await movies_repo.upsert_movie(db, _movie_data("f80-fb-anchor", "FB Anchor"))
    from backlogg.shared.external_ids import upsert_external_id

    anchor = await movies_repo.get_movie_by_slug(db, "f80-fb-anchor")
    await upsert_external_id(db, "MOVIE", anchor.id, "TMDB", "9988771")

    recommendation = {"id": 9988772, "title": "TMDB Neighbour", "release_date": "2008-07-18"}
    detail = {
        "id": 9988772,
        "title": "TMDB Neighbour",
        "original_title": "TMDB Neighbour",
        "overview": "from tmdb",
        "release_date": "2008-07-18",
        "runtime": 100,
        "original_language": "en",
        "poster_path": "/n.jpg",
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 9.0,
        "vote_count": 100,
        "genres": [],
    }
    with (
        patch.object(
            movies_service._tmdb,
            "get_movie_recommendations",
            AsyncMock(return_value=[recommendation]),
        ),
        patch.object(movies_service._tmdb, "get_movie_detail", AsyncMock(return_value=detail)),
        patch.object(movies_service._tmdb, "get_movie_credits", AsyncMock(return_value={})),
    ):
        out = await movies_service.get_similar_movies(db, "f80-fb-anchor")

    assert len(out.results) == 1
    result = out.results[0]
    assert result.title == "TMDB Neighbour"
    # The legacy path fills the new fields too, so no consumer has to know
    # which path answered.
    assert result.item_type == "MOVIE"
    assert result.reason.kind == "EXTERNAL"
    assert result.reason.source == "TMDB"
    assert result.reason.score is None


async def test_book_without_embedding_falls_back_to_the_local_tiers(db):
    """Books keep their author/genre ranking, and it says so in the reason."""
    genres = [{"name": "F80 Fallback Genre", "slug": "f80-fallback-genre"}]
    await books_repo.upsert_book(db, _book_data("f80-fb-book-anchor", "FB Book", genres))
    await books_repo.upsert_book(db, _book_data("f80-fb-book-other", "FB Other Book", genres))

    out = await books_service.get_similar_books(db, "f80-fb-book-anchor")

    assert [r.slug for r in out.results] == ["f80-fb-book-other"]
    assert out.results[0].item_type == "BOOK"
    assert out.results[0].reason.kind == "SHARED_GENRE"
    assert out.results[0].reason.source is None


async def test_unknown_slug_is_still_404_on_every_type(db):
    """The semantic rewrite does not move the 404 boundary."""
    from fastapi import HTTPException

    callers = (
        (movies_service.get_similar_movies, "Movie not found"),
        (series_service.get_similar_series, "Series not found"),
        (books_service.get_similar_books, "Book not found"),
        (games_service.get_similar_games, "Game not found"),
    )
    for caller, detail in callers:
        with pytest.raises(HTTPException) as exc:
            await caller(db, "f80-slug-that-does-not-exist")
        assert exc.value.status_code == 404
        assert exc.value.detail == detail


async def test_cross_type_query_widens_the_hnsw_window(db, crowded, no_external_calls, monkeypatch):
    """The narrowed query runs with ``hnsw.ef_search`` raised, and still works.

    ``item_types`` is a **post-filter**: pgvector walks the index, produces
    ``ef_search`` candidates and only then keeps the other types. On the real
    development catalog — 33.062 of 35.215 vectors are games — asking for the
    60 nearest non-game neighbours of a game returned **0 rows** at the default
    window of 40 and 60 rows at 1.000, so the quota reserved slots it then
    filled with games. A fixture this small cannot reproduce that cliff (the
    planner does not even use the index), so what is pinned here is that the
    ``SET LOCAL`` is issued, is accepted by Postgres, and does not change the
    answer.
    """
    monkeypatch.setattr(settings, "SIMILAR_CROSS_TYPE_QUOTA", 3)
    monkeypatch.setattr(settings, "SIMILAR_DIVERSITY_PENALTY", 0.0)
    monkeypatch.setattr(settings, "SIMILAR_FILTERED_EF_SEARCH", 1000)

    out = await movies_service.get_similar_movies(db, "f80-quota-anchor")

    assert sum(1 for r in out.results if r.item_type == "BOOK") == 3
    # The session is still usable afterwards: SET LOCAL is scoped to the
    # transaction, not leaked onto the pooled connection.
    again = await movies_service.get_similar_movies(db, "f80-quota-anchor")
    assert [r.slug for r in again.results] == [r.slug for r in out.results]
