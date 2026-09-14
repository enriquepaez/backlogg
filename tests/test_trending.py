"""Tests for GET /v1/trending — local-activity trending (feature 81).

Trending is computed from the platform's own activity (``activity_events`` +
``library_entries`` + ``user_ratings``) with exponential time decay, with a
per-type fallback to the catalog's canonical order restricted to recent
releases. There is no external fan-out left, so nothing here mocks TMDB — the
one test that used to is now the test that asserts no HTTP client is ever
constructed.

Coverage map against the feature's acceptance criteria:

- *with activity*  → ``TestLocalActivity``
- *without activity (fallback)* → ``TestFallback``
- *different period values* → ``TestPeriod`` (all four types)
- *decay*  → ``TestDecay``
- *per-type threshold* → ``TestThreshold``
- *no double counting* → ``TestNoDoubleCounting``

Plus the three issues fixed on top of it:

- *banned authors push nothing* (issue #29) → ``TestBannedAuthors``
- *the threshold counts people, not gestures* (issue #35) →
  ``TestDistinctUserThreshold``
- *the fallback runs no discarded ``COUNT(*)``* (issue #31) →
  ``TestFallbackSkipsTheDiscardedCount``
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backlogg.books import repository as books_repo
from backlogg.books.schemas import BookSortEnum
from backlogg.core.config import settings
from backlogg.feed.models import ActivityEvent
from backlogg.feed.repository import create_rating_event, create_status_completed_event
from backlogg.games import repository as games_repo
from backlogg.games.schemas import GameSortEnum
from backlogg.library.models import LibraryEntry
from backlogg.library.repository import upsert_library_entry
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.movies.schemas import MovieSortEnum
from backlogg.ratings.models import UserRating
from backlogg.ratings.repository import upsert_rating
from backlogg.series import repository as series_repo
from backlogg.series.schemas import SeriesSortEnum
from backlogg.trending import repository as trending_repo
from backlogg.trending import service as trending_service
from backlogg.users.repository import create_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the FastAPI app, using the test DB session."""
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------


def _movie_dict(
    slug: str,
    *,
    release_date: date | None = date(2023, 6, 15),
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": slug.replace("-", " ").title(),
        "original_title": slug.replace("-", " ").title(),
        "slug": slug,
        "overview": "A film.",
        "release_date": release_date,
        "runtime": 120,
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rating_external,
        "rating_count_external": 5000 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _series_dict(
    slug: str,
    *,
    first_air_date: date | None = date(2022, 9, 1),
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": slug.replace("-", " ").title(),
        "original_title": slug.replace("-", " ").title(),
        "slug": slug,
        "overview": "A show.",
        "first_air_date": first_air_date,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Returning Series",
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": rating_external,
        "rating_count_external": 4000 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book_dict(
    slug: str,
    *,
    first_publish_date: date | None = date(1950, 1, 1),
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": slug.replace("-", " ").title(),
        "original_title": None,
        "slug": slug,
        "overview": "A book.",
        "first_publish_date": first_publish_date,
        "original_language": "en",
        "poster_url": f"https://example.com/{slug}.jpg",
        "rating_external": rating_external,
        "rating_count_external": 200 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game_dict(
    slug: str,
    *,
    release_date: date | None = date(2020, 1, 1),
    rating_internal: float | None = None,
    rating_external: float | None = None,
) -> dict:
    return {
        "title": slug.replace("-", " ").title(),
        "original_title": slug.replace("-", " ").title(),
        "slug": slug,
        "overview": "A game.",
        "release_date": release_date,
        "game_type": "main_game",
        "original_language": None,
        "poster_url": f"https://example.com/{slug}.jpg",
        "backdrop_url": None,
        "rating_external": rating_external,
        "rating_count_external": 1000 if rating_external else None,
        "rating_internal": rating_internal,
        "rating_count_internal": 5 if rating_internal else 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


async def _make_movie(db, slug: str, **kwargs):
    return await movies_repo.upsert_movie(db, _movie_dict(slug, **kwargs))


async def _make_series(db, slug: str, **kwargs):
    return await series_repo.upsert_series(db, _series_dict(slug, **kwargs))


async def _make_book(db, slug: str, **kwargs):
    return await books_repo.upsert_book(db, _book_dict(slug, **kwargs))


async def _make_game(db, slug: str, **kwargs):
    return await games_repo.upsert_game(db, _game_dict(slug, **kwargs))


_seq = iter(range(10_000, 99_999))


async def _make_user(db, prefix: str = "trend", *, banned: bool = False):
    username = f"{prefix}-user-{next(_seq)}"
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
            "is_banned": banned,
        },
    )
    return user.id


# ---------------------------------------------------------------------------
# Activity helpers
#
# The whole test suite runs inside ONE database transaction, and Postgres'
# now() is the *transaction* timestamp — so an UPDATE through the ORM cannot
# produce ``updated_at > created_at`` here the way a second HTTP request would
# in production. Activity rows are therefore inserted directly with explicit
# timestamps whenever a specific age matters; ``TestNoDoubleCounting`` uses the
# real production helpers instead, precisely because it must not fake anything.
# ---------------------------------------------------------------------------


async def _add_event(db, *, user_id, item_type, item_id, event_type, age, rating_id=None):
    db.add(
        ActivityEvent(
            user_id=user_id,
            event_type=event_type,
            item_type=item_type,
            item_id=item_id,
            rating_id=rating_id,
            created_at=datetime.now(UTC) - age,
        )
    )
    await db.flush()


async def _add_library_entry(db, *, user_id, item_type, item_id, status, age):
    ts = datetime.now(UTC) - age
    db.add(
        LibraryEntry(
            user_id=user_id,
            item_type=item_type,
            item_id=item_id,
            status=status,
            created_at=ts,
            updated_at=ts,
        )
    )
    await db.flush()


async def _add_rating(
    db, *, user_id, item_type, item_id, age, score=4, is_hidden=False, re_rated=False
):
    """Insert a user_ratings row with a controlled age.

    ``re_rated=True`` back-dates ``created_at`` beyond ``updated_at`` so the row
    looks like a rating that was edited later — the only shape that counts as a
    re-engagement gesture.
    """
    updated_at = datetime.now(UTC) - age
    created_at = updated_at - timedelta(days=30) if re_rated else updated_at
    rating = UserRating(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        score=score,
        review_text=None,
        is_hidden=is_hidden,
        created_at=created_at,
        updated_at=updated_at,
    )
    db.add(rating)
    await db.flush()
    return rating


async def _burst(db, *, item_type, item_id, count, age, status="want", banned=False):
    """``count`` distinct users adding the item to their backlog, all ``age`` old."""
    for _ in range(count):
        user_id = await _make_user(db, banned=banned)
        await _add_library_entry(
            db, user_id=user_id, item_type=item_type, item_id=item_id, status=status, age=age
        )


def _slugs(body: dict) -> list[str]:
    return [r["slug"] for r in body["results"]]


# ---------------------------------------------------------------------------
# Contract: shape of the response is unchanged
# ---------------------------------------------------------------------------


async def test_trending_returns_200_with_results_array(client, db):
    await _make_movie(db, "shape-movie", rating_internal=4.0)
    response = await client.get("/v1/trending")
    assert response.status_code == 200
    assert isinstance(response.json()["results"], list)


async def test_trending_invalid_type_returns_422(client, db):
    response = await client.get("/v1/trending?type=invalid")
    assert response.status_code == 422


async def test_trending_invalid_period_returns_422(client, db):
    response = await client.get("/v1/trending?period=month")
    assert response.status_code == 422


async def test_trending_book_and_game_types_are_accepted(client, db):
    assert (await client.get("/v1/trending?type=book")).status_code == 200
    assert (await client.get("/v1/trending?type=game")).status_code == 200


async def test_trending_result_fields(client, db):
    """Each result still carries the same seven fields (features 20/69)."""
    await _make_movie(db, "fields-movie", rating_internal=4.2, rating_external=7.8)

    response = await client.get("/v1/trending?type=movie")

    assert response.status_code == 200
    item = next(r for r in response.json()["results"] if r["slug"] == "fields-movie")
    for field in (
        "item_type",
        "title",
        "slug",
        "poster_url",
        "release_date",
        "rating_external",
        "rating_internal",
    ):
        assert field in item, f"Missing field: {field}"
    assert item["item_type"] == "MOVIE"
    assert item["rating_internal"] == 4.2
    assert item["rating_external"] == 7.8


async def test_trending_type_filter_returns_only_that_type(client, db):
    await _make_movie(db, "only-movie", rating_internal=4.0)
    await _make_series(db, "only-series", rating_internal=4.0)

    body = (await client.get("/v1/trending?type=movie")).json()
    assert body["results"]
    assert all(r["item_type"] == "MOVIE" for r in body["results"])


async def test_trending_no_type_mixes_four_types(client, db):
    await _make_movie(db, "mix-movie", rating_internal=4.0)
    await _make_series(db, "mix-series", rating_internal=4.0)
    await _make_book(db, "mix-book", rating_internal=4.0)
    await _make_game(db, "mix-game", rating_internal=4.0)

    body = (await client.get("/v1/trending")).json()

    assert {r["item_type"] for r in body["results"]} == {"MOVIE", "SERIES", "BOOK", "GAME"}
    assert len(body["results"]) <= 20


async def test_trending_caps_at_20_items(client, db):
    for i in range(25):
        await _make_book(db, f"cap-book-{i:02d}", rating_internal=1.0 + i / 100)

    body = (await client.get("/v1/trending?type=book")).json()

    assert len(body["results"]) == 20


async def test_trending_makes_no_external_calls(client, db):
    """Acceptance criterion 1: no external API is contacted, for any type.

    Asserted at the transport boundary rather than by mocking a named adapter,
    so it keeps holding if someone reintroduces a fan-out through a different
    client.
    """
    await _make_movie(db, "no-http-movie", rating_internal=4.0)
    await _make_series(db, "no-http-series", rating_internal=4.0)
    await _make_book(db, "no-http-book", rating_internal=4.0)
    await _make_game(db, "no-http-game", rating_internal=4.0)

    # Every adapter builds its own ``httpx.AsyncClient`` per call, so blowing up
    # the constructor catches any fan-out. The test client itself was already
    # built by the fixture, so it keeps working.
    with patch.object(
        httpx.AsyncClient, "__init__", side_effect=AssertionError("external HTTP call")
    ):
        for url in (
            "/v1/trending",
            "/v1/trending?type=movie",
            "/v1/trending?type=series",
            "/v1/trending?type=book",
            "/v1/trending?type=game",
        ):
            assert (await client.get(url)).status_code == 200


def test_tmdb_adapters_no_longer_expose_trending():
    """The TMDB trending fan-out was retired with its last caller (feature 81)."""
    from backlogg.movies.adapters.tmdb import TMDBClient
    from backlogg.series.adapters.tmdb import TMDBSeriesClient

    assert not hasattr(TMDBClient, "get_trending_movies")
    assert not hasattr(TMDBSeriesClient, "get_trending_series")


# ---------------------------------------------------------------------------
# Fallback — no activity at all
# ---------------------------------------------------------------------------


class TestFallback:
    """With an empty platform every type falls back to the catalog's canonical
    order (feature 66) restricted to recent releases."""

    async def test_book_fallback_ranks_by_rating_internal_then_external(self, client, db):
        await _make_book(db, "fb-book-low", rating_internal=2.0, rating_external=9.0)
        await _make_book(db, "fb-book-high", rating_internal=4.5, rating_external=1.0)
        await _make_book(db, "fb-book-none", rating_internal=None, rating_external=None)

        slugs = _slugs((await client.get("/v1/trending?type=book")).json())

        assert slugs.index("fb-book-high") < slugs.index("fb-book-low")
        assert slugs.index("fb-book-low") < slugs.index("fb-book-none")

    async def test_game_fallback_ranks_by_rating_internal_then_external(self, client, db):
        await _make_game(db, "fb-game-low", rating_internal=2.0, rating_external=9.5)
        await _make_game(db, "fb-game-high", rating_internal=4.8, rating_external=1.0)

        slugs = _slugs((await client.get("/v1/trending?type=game")).json())

        assert slugs.index("fb-game-high") < slugs.index("fb-game-low")

    async def test_movie_fallback_ranks_by_rating_internal_then_external(self, client, db):
        await _make_movie(db, "fb-movie-low", rating_internal=2.0, rating_external=9.0)
        await _make_movie(db, "fb-movie-high", rating_internal=4.5, rating_external=1.0)

        slugs = _slugs((await client.get("/v1/trending?type=movie")).json())

        assert slugs.index("fb-movie-high") < slugs.index("fb-movie-low")

    async def test_series_fallback_ranks_by_rating_internal_then_external(self, client, db):
        await _make_series(db, "fb-series-low", rating_internal=2.0, rating_external=9.0)
        await _make_series(db, "fb-series-high", rating_internal=4.5, rating_external=1.0)

        slugs = _slugs((await client.get("/v1/trending?type=series")).json())

        assert slugs.index("fb-series-high") < slugs.index("fb-series-low")

    async def test_activity_below_threshold_still_falls_back(self, client, db):
        """A trickle of activity is not a ranking: below TRENDING_MIN_ACTIVITY
        the type keeps using the catalog order, so a barely-touched bad item
        cannot outrank a well-rated one."""
        popular = await _make_book(db, "fb-thin-popular", rating_internal=4.9)
        touched = await _make_book(db, "fb-thin-touched", rating_internal=1.0)
        assert settings.TRENDING_MIN_ACTIVITY > 1
        await _burst(db, item_type="BOOK", item_id=touched.id, count=1, age=timedelta(minutes=5))

        slugs = _slugs((await client.get("/v1/trending?type=book")).json())

        assert slugs.index("fb-thin-popular") < slugs.index("fb-thin-touched")
        assert popular.slug in slugs

    async def test_empty_release_window_relaxes_instead_of_returning_a_hole(self, client, db):
        """Edge case: no release of this type inside the window.

        The window is a preference, not a hard filter, in the fallback — a hole
        in the response is worse for the caller than a slightly older item, and
        for books (whose date is the *original* publication year) an empty
        window is the normal case. So the window is dropped entirely rather
        than returning nothing.
        """
        await _make_book(db, "fb-ancient-book", first_publish_date=date(1927, 1, 1))

        body = (await client.get("/v1/trending?type=book&period=day")).json()

        assert _slugs(body) == ["fb-ancient-book"]

    async def test_item_without_a_release_date_is_only_reachable_after_relaxing(self, client, db):
        """A NULL date cannot satisfy ``date >= cutoff``, so such items only
        surface through the relaxed pass — they are never silently dropped when
        they are all the catalog has."""
        await _make_game(db, "fb-undated-game", release_date=None, rating_internal=3.0)

        body = (await client.get("/v1/trending?type=game&period=week")).json()

        assert _slugs(body) == ["fb-undated-game"]


# ---------------------------------------------------------------------------
# period — real effect for the four types
# ---------------------------------------------------------------------------


class TestPeriod:
    """``period`` drives two windows: the activity window (1d / 7d) and the
    fallback's release window (90d / 365d). Both are ``WHERE`` filters, never
    an ``ORDER BY``, which is what makes the parameter observable even with an
    empty platform — the state this project is actually in.

    Feature 68 left ``period`` inert for book/game; these four tests are the
    debt being repaid, so all four types are asserted.
    """

    @staticmethod
    def _recent() -> date:
        return (datetime.now(UTC) - timedelta(days=30)).date()

    @staticmethod
    def _old() -> date:
        return (datetime.now(UTC) - timedelta(days=200)).date()

    async def test_period_narrows_the_movie_release_window(self, client, db):
        await _make_movie(db, "per-movie-recent", release_date=self._recent(), rating_internal=3.0)
        await _make_movie(db, "per-movie-old", release_date=self._old(), rating_internal=5.0)

        day = _slugs((await client.get("/v1/trending?type=movie&period=day")).json())
        week = _slugs((await client.get("/v1/trending?type=movie&period=week")).json())

        assert day == ["per-movie-recent"]
        assert set(week) == {"per-movie-recent", "per-movie-old"}

    async def test_period_narrows_the_series_release_window(self, client, db):
        await _make_series(
            db, "per-series-recent", first_air_date=self._recent(), rating_internal=3.0
        )
        await _make_series(db, "per-series-old", first_air_date=self._old(), rating_internal=5.0)

        day = _slugs((await client.get("/v1/trending?type=series&period=day")).json())
        week = _slugs((await client.get("/v1/trending?type=series&period=week")).json())

        assert day == ["per-series-recent"]
        assert set(week) == {"per-series-recent", "per-series-old"}

    async def test_period_narrows_the_book_release_window(self, client, db):
        await _make_book(
            db, "per-book-recent", first_publish_date=self._recent(), rating_internal=3.0
        )
        await _make_book(db, "per-book-old", first_publish_date=self._old(), rating_internal=5.0)

        day = _slugs((await client.get("/v1/trending?type=book&period=day")).json())
        week = _slugs((await client.get("/v1/trending?type=book&period=week")).json())

        assert day == ["per-book-recent"]
        assert set(week) == {"per-book-recent", "per-book-old"}

    async def test_period_narrows_the_game_release_window(self, client, db):
        await _make_game(db, "per-game-recent", release_date=self._recent(), rating_internal=3.0)
        await _make_game(db, "per-game-old", release_date=self._old(), rating_internal=5.0)

        day = _slugs((await client.get("/v1/trending?type=game&period=day")).json())
        week = _slugs((await client.get("/v1/trending?type=game&period=week")).json())

        assert day == ["per-game-recent"]
        assert set(week) == {"per-game-recent", "per-game-old"}

    async def test_period_narrows_the_activity_window(self, client, db):
        """Activity three days old is inside ``week`` but outside ``day``."""
        fresh = await _make_book(db, "per-act-fresh", rating_internal=1.0)
        stale = await _make_book(db, "per-act-stale", rating_internal=5.0)
        await _burst(db, item_type="BOOK", item_id=fresh.id, count=6, age=timedelta(hours=2))
        await _burst(db, item_type="BOOK", item_id=stale.id, count=6, age=timedelta(days=3))

        day = _slugs((await client.get("/v1/trending?type=book&period=day")).json())
        week = _slugs((await client.get("/v1/trending?type=book&period=week")).json())

        # period=day only sees the 2h-old burst → the stale item drops out of
        # the ranking and only reappears through the catalog fallback ordering.
        assert day[0] == "per-act-fresh"
        # period=week sees both bursts; the fresher one still leads thanks to decay.
        assert week[0] == "per-act-fresh"
        assert "per-act-stale" in week

    async def test_default_period_is_week(self, client, db):
        await _make_movie(db, "per-default-recent", release_date=self._recent())
        await _make_movie(db, "per-default-old", release_date=self._old())

        default = _slugs((await client.get("/v1/trending?type=movie")).json())
        week = _slugs((await client.get("/v1/trending?type=movie&period=week")).json())

        assert set(default) == set(week) == {"per-default-recent", "per-default-old"}


# ---------------------------------------------------------------------------
# Local activity ranking
# ---------------------------------------------------------------------------


class TestLocalActivity:
    async def test_activity_outranks_the_catalog_order(self, client, db):
        """Above the threshold the local signal wins: a poorly rated item with
        real engagement leads over a highly rated one nobody touched."""
        loved = await _make_movie(db, "act-loved-but-quiet", rating_internal=5.0)
        busy = await _make_movie(db, "act-busy-but-mediocre", rating_internal=1.0)
        await _burst(db, item_type="MOVIE", item_id=busy.id, count=6, age=timedelta(minutes=10))

        slugs = _slugs((await client.get("/v1/trending?type=movie")).json())

        assert slugs[0] == "act-busy-but-mediocre"
        assert loved.slug not in slugs  # the local ranking replaces the catalog one

    async def test_more_activity_ranks_higher(self, client, db):
        hot = await _make_game(db, "act-hot-game")
        warm = await _make_game(db, "act-warm-game")
        await _burst(db, item_type="GAME", item_id=hot.id, count=6, age=timedelta(minutes=10))
        await _burst(db, item_type="GAME", item_id=warm.id, count=2, age=timedelta(minutes=10))

        slugs = _slugs((await client.get("/v1/trending?type=game")).json())

        assert slugs.index("act-hot-game") < slugs.index("act-warm-game")

    async def test_ratings_weigh_more_than_backlog_intent(self, client, db):
        rated = await _make_book(db, "act-rated-book")
        wanted = await _make_book(db, "act-wanted-book")
        for _ in range(3):
            user_id = await _make_user(db)
            rating = await _add_rating(
                db, user_id=user_id, item_type="BOOK", item_id=rated.id, age=timedelta(minutes=5)
            )
            await _add_event(
                db,
                user_id=user_id,
                item_type="BOOK",
                item_id=rated.id,
                event_type="rating_created",
                age=timedelta(minutes=5),
                rating_id=rating.id,
            )
        await _burst(db, item_type="BOOK", item_id=wanted.id, count=3, age=timedelta(minutes=5))

        slugs = _slugs((await client.get("/v1/trending?type=book")).json())

        assert slugs.index("act-rated-book") < slugs.index("act-wanted-book")

    async def test_hidden_review_does_not_push_an_item(self, db):
        """Moderation must not be routed around: a hidden review contributes
        neither its event nor its own row."""
        item = await _make_series(db, "act-hidden-series")
        user_ids = []
        for _ in range(6):
            user_id = await _make_user(db)
            user_ids.append(user_id)
            rating = await _add_rating(
                db,
                user_id=user_id,
                item_type="SERIES",
                item_id=item.id,
                age=timedelta(minutes=5),
                is_hidden=True,
            )
            await _add_event(
                db,
                user_id=user_id,
                item_type="SERIES",
                item_id=item.id,
                event_type="rating_created",
                age=timedelta(minutes=5),
                rating_id=rating.id,
            )

        signal = await trending_repo.activity_scores(
            db,
            item_type="SERIES",
            since=datetime.now(UTC) - timedelta(days=7),
            now=datetime.now(UTC),
            half_life_seconds=42 * 3600,
            limit=20,
        )

        assert signal.total_gestures == 0
        assert signal.scored == []

    async def test_activity_on_a_deleted_catalog_row_is_dropped_not_fatal(self, client, db):
        """The activity tables are polymorphic and carry no FK, so an item id
        can outlive its catalog row. That must not 500 the endpoint."""
        alive = await _make_game(db, "act-alive-game")
        await _burst(db, item_type="GAME", item_id=alive.id, count=6, age=timedelta(minutes=5))
        await _burst(db, item_type="GAME", item_id=987654321, count=6, age=timedelta(minutes=5))

        response = await client.get("/v1/trending?type=game")

        assert response.status_code == 200
        assert _slugs(response.json()) == ["act-alive-game"]


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------


class TestDecay:
    async def test_fresh_small_activity_beats_old_large_activity(self, client, db):
        """Six days of decay (≈3.4 half-lives at period=week) leave a 5-gesture
        burst worth less than a single fresh gesture. Without decay the older,
        larger burst would win — that is the whole point of the feature."""
        old = await _make_book(db, "decay-old-burst")
        fresh = await _make_book(db, "decay-fresh-touch")
        await _burst(db, item_type="BOOK", item_id=old.id, count=5, age=timedelta(days=6))
        await _burst(db, item_type="BOOK", item_id=fresh.id, count=1, age=timedelta(minutes=1))

        slugs = _slugs((await client.get("/v1/trending?type=book&period=week")).json())

        assert slugs.index("decay-fresh-touch") < slugs.index("decay-old-burst")

    async def test_one_half_life_halves_the_contribution(self, db):
        """The decay is exponential with a named half-life, not a disguised
        ``ORDER BY created_at``: at exactly one half-life the score is half."""
        item = await _make_book(db, "decay-half-life")
        half_life = timedelta(hours=42)
        now = datetime.now(UTC)
        await _burst(db, item_type="BOOK", item_id=item.id, count=1, age=timedelta(seconds=0))

        fresh = await trending_repo.activity_scores(
            db,
            item_type="BOOK",
            since=now - timedelta(days=7),
            now=now,
            half_life_seconds=half_life.total_seconds(),
            limit=20,
        )
        aged = await trending_repo.activity_scores(
            db,
            item_type="BOOK",
            since=now - timedelta(days=7),
            now=now + half_life,
            half_life_seconds=half_life.total_seconds(),
            limit=20,
        )

        assert aged.scored[0][1] == pytest.approx(fresh.scored[0][1] / 2, rel=1e-6)


# ---------------------------------------------------------------------------
# Per-type threshold
# ---------------------------------------------------------------------------


class TestThreshold:
    async def test_threshold_is_evaluated_per_type_in_the_same_response(self, client, db):
        """Decision 3: the threshold is per type, not global. One type above it
        serves local signal while another below it falls back — in the same
        response, so the community can start with one kind of content."""
        busy_book = await _make_book(db, "thr-book-busy", rating_internal=1.0)
        quiet_book = await _make_book(db, "thr-book-quiet", rating_internal=5.0)
        busy_game = await _make_game(db, "thr-game-touched", rating_internal=1.0)
        quiet_game = await _make_game(db, "thr-game-quiet", rating_internal=5.0)

        await _burst(db, item_type="BOOK", item_id=busy_book.id, count=6, age=timedelta(minutes=5))
        await _burst(db, item_type="GAME", item_id=busy_game.id, count=1, age=timedelta(minutes=5))

        body = (await client.get("/v1/trending")).json()
        slugs = _slugs(body)

        # BOOK is above the threshold → local ranking: the busy, badly rated
        # book is the only book, the well-rated untouched one is gone.
        assert busy_book.slug in slugs
        assert quiet_book.slug not in slugs
        # GAME is below it → catalog fallback: the well-rated one leads.
        assert slugs.index(quiet_game.slug) < slugs.index(busy_game.slug)

    async def test_threshold_is_configurable(self, client, db, monkeypatch):
        """Acceptance criterion 4 — the minimum is read from settings, so an
        operator can raise or lower it without a code change."""
        busy = await _make_movie(db, "thr-cfg-busy", rating_internal=1.0)
        quiet = await _make_movie(db, "thr-cfg-quiet", rating_internal=5.0)
        await _burst(db, item_type="MOVIE", item_id=busy.id, count=3, age=timedelta(minutes=5))

        monkeypatch.setattr(settings, "TRENDING_MIN_ACTIVITY", 99)
        high = _slugs((await client.get("/v1/trending?type=movie")).json())

        from backlogg.core.cache import get_cache

        get_cache().clear()
        monkeypatch.setattr(settings, "TRENDING_MIN_ACTIVITY", 2)
        low = _slugs((await client.get("/v1/trending?type=movie")).json())

        assert high.index(quiet.slug) < high.index(busy.slug)  # fallback order
        assert low == [busy.slug]  # local ranking


# ---------------------------------------------------------------------------
# No double counting
# ---------------------------------------------------------------------------


class TestNoDoubleCounting:
    """``activity_events`` mirrors the other two tables, so the three of them
    must be trimmed into disjoint contributions before being summed.

    These tests deliberately go through the **production** write helpers (the
    same calls ``ratings/service.py`` and ``library/service.py`` make) rather
    than inserting rows by hand: faking the rows would also fake the overlap
    the tests exist to catch.
    """

    async def _gestures(self, db, item_type: str) -> int:
        signal = await trending_repo.activity_scores(
            db,
            item_type=item_type,
            since=datetime.now(UTC) - timedelta(days=7),
            now=datetime.now(UTC),
            half_life_seconds=42 * 3600,
            limit=20,
        )
        return signal.total_gestures

    async def test_a_rating_counts_once_not_twice(self, db):
        """A rating writes a ``user_ratings`` row *and* a ``rating_created``
        event. Counting both would double the weight of one click."""
        movie = await _make_movie(db, "dup-rating-movie")
        user_id = await _make_user(db)

        rating = await upsert_rating(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=4, review_text=None
        )
        await create_rating_event(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, rating_id=rating.id
        )

        assert await self._gestures(db, "MOVIE") == 1

    async def test_a_completion_counts_once_not_twice(self, db):
        """A completion writes a ``library_entries`` row *and* a
        ``status_completed`` event."""
        movie = await _make_movie(db, "dup-completion-movie")
        user_id = await _make_user(db)

        await upsert_library_entry(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="completed"
        )
        await create_status_completed_event(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id
        )

        assert await self._gestures(db, "MOVIE") == 1

    async def test_rating_plus_completion_by_the_same_user_counts_twice(self, db):
        """Two distinct gestures are two gestures — de-duplication must not
        turn into under-counting."""
        movie = await _make_movie(db, "dup-both-movie")
        user_id = await _make_user(db)

        rating = await upsert_rating(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, score=4, review_text=None
        )
        await create_rating_event(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, rating_id=rating.id
        )
        await upsert_library_entry(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status="completed"
        )
        await create_status_completed_event(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id
        )

        assert await self._gestures(db, "MOVIE") == 2

    async def test_backlog_intent_counts_because_it_emits_no_event(self, db):
        """``want``/``in_progress``/``dropped`` never produce an event, so they
        are the part of ``library_entries`` that adds signal instead of noise."""
        movie = await _make_movie(db, "dup-intent-movie")
        for status in ("want", "in_progress", "dropped"):
            user_id = await _make_user(db)
            await upsert_library_entry(
                db, user_id=user_id, item_type="MOVIE", item_id=movie.id, status=status
            )

        assert await self._gestures(db, "MOVIE") == 3

    async def test_a_re_rating_adds_exactly_one_gesture(self, db):
        """Editing a rating produces no second event
        (``uq_activity_events_rating_id``), but it *is* fresh engagement — so
        it is counted once, from ``user_ratings`` only."""
        book = await _make_book(db, "dup-rerate-book")
        user_id = await _make_user(db)
        rating = await _add_rating(
            db,
            user_id=user_id,
            item_type="BOOK",
            item_id=book.id,
            age=timedelta(minutes=5),
            re_rated=True,
        )
        await _add_event(
            db,
            user_id=user_id,
            item_type="BOOK",
            item_id=book.id,
            event_type="rating_created",
            age=timedelta(days=30),
            rating_id=rating.id,
        )

        # The creation event is 30 days old → outside the 7-day window. Only
        # the edit falls inside it, and it is counted exactly once.
        assert await self._gestures(db, "BOOK") == 1

    async def test_a_fresh_rating_is_not_also_counted_as_a_re_rating(self, db):
        """``updated_at == created_at`` is a creation, already counted through
        its event — it must not be picked up a second time as an edit."""
        book = await _make_book(db, "dup-fresh-book")
        user_id = await _make_user(db)
        rating = await _add_rating(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, age=timedelta(minutes=5)
        )
        await _add_event(
            db,
            user_id=user_id,
            item_type="BOOK",
            item_id=book.id,
            event_type="rating_created",
            age=timedelta(minutes=5),
            rating_id=rating.id,
        )

        assert await self._gestures(db, "BOOK") == 1

    async def test_giving_content_to_an_empty_rating_is_one_gesture_not_two(self, db):
        """The case the first pass got wrong (review of feature 81).

        ``rate_item`` only writes the ``rating_created`` event when the rating
        has content (``backlogg/ratings/service.py``), and ``RatingIn`` allows
        both fields to be ``None`` — so ``PUT {}`` is a valid request. That
        splits creation of the row from creation of its event:

        1. ``PUT {}`` at T0 → ``user_ratings`` row, **no** event.
        2. ``PUT {"score": 4}`` at T1 → **one** action that both creates the
           event *and* leaves ``updated_at (T1) > created_at (T0)``.

        Counting the row as an edit on top of its own event would score that
        single action twice (weight 4.0 instead of 3.0) and inflate the
        ``TRENDING_MIN_ACTIVITY`` counter. The event belongs to the very edit
        that produced it, so the edit is not extra signal.

        Both timestamps are inside the window here — that is exactly what the
        two neighbouring tests do not cover.
        """
        book = await _make_book(db, "dup-empty-then-content-book")
        user_id = await _make_user(db)

        # Step 1 — PUT {}: production writer, and no event (score/review null).
        rating = await upsert_rating(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, score=None, review_text=None
        )
        # Postgres' now() is the *transaction* timestamp and the whole suite
        # runs in one transaction, so the T0/T1 gap a second HTTP request would
        # produce has to be introduced by hand. Back-dating created_at is
        # enough: the BEFORE UPDATE trigger re-stamps updated_at to now() on
        # its own, which is precisely the shape step 2 leaves behind.
        rating.created_at = datetime.now(UTC) - timedelta(hours=5)
        await db.flush()

        # Step 2 — PUT {"score": 4}: the same two production calls rate_item makes.
        rating = await upsert_rating(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, score=4, review_text=None
        )
        await create_rating_event(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, rating_id=rating.id
        )

        assert rating.updated_at > rating.created_at  # the shape that used to double count
        assert await self._gestures(db, "BOOK") == 1

    async def test_an_edit_after_a_rating_that_already_had_its_event_counts_twice(self, db):
        """The legitimate case the fix must not break.

        "I scored it at T0 (event written at T0), I came back at T1 and edited
        the review" is two gestures, and must stay two. The discriminator is
        whether the edit happened *after* the event, not merely after the row.
        """
        book = await _make_book(db, "dup-edit-after-event-book")
        user_id = await _make_user(db)

        rating = await upsert_rating(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, score=4, review_text=None
        )
        await create_rating_event(
            db, user_id=user_id, item_type="BOOK", item_id=book.id, rating_id=rating.id
        )

        # Push the original rating *and its event* back to T0, leaving
        # updated_at at the transaction's now() to stand for the T1 edit.
        t0 = datetime.now(UTC) - timedelta(hours=5)
        rating.created_at = t0
        await db.flush()
        event = (
            await db.execute(select(ActivityEvent).where(ActivityEvent.rating_id == rating.id))
        ).scalar_one()
        event.created_at = t0
        await db.flush()

        assert await self._gestures(db, "BOOK") == 2

    async def _toggle_completed(
        self, db, *, user_id: int, item_id: int, laps: int, end_status: str = "completed"
    ) -> None:
        """``completed → dropped`` ``laps`` times, ending on ``end_status``.

        Exactly the two calls ``library/service.set_library_status`` makes on a
        transition into ``completed`` (upsert the entry, write the event), and
        only the upsert on the way out — which is what makes every lap leave a
        new ``status_completed`` row behind.

        ``end_status`` is not a detail: ending on ``dropped`` leaves the
        library row in a status that *does* contribute (contribution 2) while
        the ``status_completed`` event of the same user and item is still
        inside the window, which is the second half of issue #30.
        """
        for lap in range(laps):
            await upsert_library_entry(
                db, user_id=user_id, item_type="MOVIE", item_id=item_id, status="completed"
            )
            await create_status_completed_event(
                db, user_id=user_id, item_type="MOVIE", item_id=item_id
            )
            if lap < laps - 1 or end_status == "dropped":
                await upsert_library_entry(
                    db, user_id=user_id, item_type="MOVIE", item_id=item_id, status="dropped"
                )

    async def test_toggling_completed_over_and_over_is_still_one_gesture(self, db):
        """Issue #30: the toggle has no ceiling in ``activity_events``.

        ``uq_activity_events_rating_id`` does not constrain these rows — they
        carry ``rating_id NULL`` and Postgres allows any number of NULLs — so
        every lap back into ``completed`` writes another event. The writer is
        deliberately left alone (each transition stays its own fact in the
        feed); trending is what must stop counting the laps.
        """
        movie = await _make_movie(db, "dup-toggle-movie")
        user_id = await _make_user(db)

        await self._toggle_completed(db, user_id=user_id, item_id=movie.id, laps=6)

        raw_rows = (
            await db.execute(
                select(func.count())
                .select_from(ActivityEvent)
                .where(ActivityEvent.user_id == user_id, ActivityEvent.item_id == movie.id)
            )
        ).scalar_one()
        assert raw_rows == 6, "the writer is unchanged: every lap still leaves an event"

        # ...and all six collapse into the single gesture they really are.
        assert await self._gestures(db, "MOVIE") == 1

    async def test_a_cycle_that_ends_in_dropped_is_still_one_gesture(self, db):
        """The other half of issue #30: the overlap is *between* contributions.

        Contribution 2 excludes ``completed`` because that status is already
        counted as ``status_completed`` — but a cycle does not end where it
        started. After ``completed → dropped`` the library row sits in
        ``dropped`` (a counting status) while the event written on the way in
        is still inside the window, so the same user pays twice for one
        back-and-forth: 2.0 for the event plus 0.5 for the intent. One user, one
        item, one gesture — whichever status the cycle happens to stop on.
        """
        movie = await _make_movie(db, "dup-cycle-dropped-movie")
        user_id = await _make_user(db)

        await self._toggle_completed(
            db, user_id=user_id, item_id=movie.id, laps=4, end_status="dropped"
        )

        assert await self._gestures(db, "MOVIE") == 1

    async def test_a_lone_toggling_user_cannot_cross_the_threshold(self, client, db, monkeypatch):
        """The manipulation vector itself: one account, no community.

        Left on ``dropped``, the cycle used to pay **twice** per item (2.0 for
        the event plus 0.5 for the intent), so half as many items as the
        threshold were enough for a single user to hand the whole type over to
        their own backlog. The item count below is chosen to sit exactly on
        that edge: ``2 * items >= TRENDING_MIN_ACTIVITY`` (it crossed before the
        fix) and ``items < TRENDING_MIN_ACTIVITY`` (it must not cross now that
        each item is worth one gesture). With the default of 5 that is the
        three-item case from the review of this fix.

        A single account can still contribute one gesture per *distinct* item —
        that is the design, and it costs a real item every time. What it can no
        longer do is multiply its weight on the items it already touched.

        ``TRENDING_MIN_USERS`` is pinned to 1 here on purpose, and removing
        that line would quietly gut the test. This case is one account, so the
        people minimum added for issue #35 rejects it before the gesture count
        is even consulted — measured in review: with the real default of 3 this
        test stopped failing when the ``GROUP BY`` that collapses the laps was
        removed, because the fallback was already being chosen for an unrelated
        reason. The invariant itself is still pinned by the repository-level
        tests above; what the pin restores is its end-to-end mirror, which is
        the only place the *gesture* threshold is exercised against the toggle.
        """
        monkeypatch.setattr(settings, "TRENDING_MIN_USERS", 1)
        quiet = await _make_movie(db, "dup-toggle-quiet", rating_internal=5.0)
        user_id = await _make_user(db)
        item_count = (settings.TRENDING_MIN_ACTIVITY + 1) // 2
        toggled = []
        for n in range(item_count):
            movie = await _make_movie(db, f"dup-toggle-solo-{n}", rating_internal=1.0)
            toggled.append(movie)
            await self._toggle_completed(
                db, user_id=user_id, item_id=movie.id, laps=2, end_status="dropped"
            )

        slugs = _slugs((await client.get("/v1/trending?type=movie")).json())

        assert quiet.slug in slugs, "the fallback must still list the untouched movie"
        for movie in toggled:
            assert slugs.index(quiet.slug) < slugs.index(movie.slug)

    async def test_distinct_users_completing_the_same_item_each_count(self, db):
        """The de-duplication is per user, not per item — otherwise the fix
        would silence exactly the signal trending exists to measure: several
        different people finishing the same thing at the same time."""
        movie = await _make_movie(db, "dup-many-users-movie")

        for _ in range(3):
            user_id = await _make_user(db)
            await self._toggle_completed(db, user_id=user_id, item_id=movie.id, laps=4)

        assert await self._gestures(db, "MOVIE") == 3


# ---------------------------------------------------------------------------
# Windows and half-lives are named, not magic
# ---------------------------------------------------------------------------


def test_periods_cover_exactly_the_two_supported_values():
    """FE-68 is built against ``day``/``week``; the enum must not drift."""
    assert set(trending_service.ACTIVITY_WINDOWS) == {"day", "week"}
    assert set(trending_service.DECAY_HALF_LIVES) == {"day", "week"}
    assert set(trending_service.FALLBACK_WINDOWS) == {"day", "week"}


def test_decay_half_life_is_shorter_than_its_window():
    """A half-life at or beyond the window edge would make the decay
    unobservable — the ranking would degenerate into a raw count."""
    for period, window in trending_service.ACTIVITY_WINDOWS.items():
        assert trending_service.DECAY_HALF_LIVES[period] < window


# ---------------------------------------------------------------------------
# Moderation: a banned author pushes nothing (issue #29)
# ---------------------------------------------------------------------------


class TestBannedAuthors:
    """``visible_review_filters()`` says a banned author disappears from every
    surface that lists or aggregates reviews. Trending aggregates *three*
    tables, so the exclusion has to hold on all three contributions — the
    events, the backlog intent and the rating edits — and on the threshold,
    which is computed over the same rows.

    Banning removes a user's influence over what the front page shows, not
    just their reviews: that is the decision these tests pin.
    """

    async def _signal(self, db, item_type: str):
        now = datetime.now(UTC)
        return await trending_repo.activity_scores(
            db,
            item_type=item_type,
            since=now - timedelta(days=7),
            now=now,
            half_life_seconds=42 * 3600,
            limit=20,
        )

    async def test_a_banned_authors_rating_event_does_not_count(self, db):
        """Contribution 1, ``rating_created``: the rating's own visibility is
        not the only thing that matters — the author's is too."""
        movie = await _make_movie(db, "ban-rating-movie")
        user_id = await _make_user(db, banned=True)
        rating = await _add_rating(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, age=timedelta(minutes=5)
        )
        await _add_event(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            event_type="rating_created",
            age=timedelta(minutes=5),
            rating_id=rating.id,
        )

        signal = await self._signal(db, "MOVIE")

        assert signal.total_gestures == 0
        assert signal.scored == []

    async def test_a_banned_authors_completion_event_does_not_count(self, db):
        """Contribution 1, ``status_completed``: these rows carry
        ``rating_id NULL``, so the author filter cannot ride on the rating
        join — it has to be the **event's** own ``user_id``."""
        series = await _make_series(db, "ban-completion-series")
        user_id = await _make_user(db, banned=True)
        await _add_event(
            db,
            user_id=user_id,
            item_type="SERIES",
            item_id=series.id,
            event_type="status_completed",
            age=timedelta(minutes=5),
        )

        signal = await self._signal(db, "SERIES")

        assert signal.total_gestures == 0

    async def test_a_banned_users_backlog_intent_does_not_count(self, db):
        """Contribution 2: ``library_entries`` has no moderation flag of its
        own, so the only thing that can retire these rows is their owner."""
        book = await _make_book(db, "ban-intent-book")
        await _burst(
            db,
            item_type="BOOK",
            item_id=book.id,
            count=6,
            age=timedelta(minutes=5),
            banned=True,
        )

        signal = await self._signal(db, "BOOK")

        assert signal.total_gestures == 0

    async def test_a_banned_users_rating_edit_does_not_count(self, db):
        """Contribution 3: the one that literally reuses
        ``visible_review_filters()`` — it lists/aggregates ``user_ratings``."""
        game = await _make_game(db, "ban-edit-game")
        user_id = await _make_user(db, banned=True)
        await _add_rating(
            db,
            user_id=user_id,
            item_type="GAME",
            item_id=game.id,
            age=timedelta(minutes=5),
            re_rated=True,
        )

        signal = await self._signal(db, "GAME")

        assert signal.total_gestures == 0

    async def test_an_active_users_gestures_survive_next_to_a_banned_ones(self, db):
        """The exclusion must cut the banned author's rows only.

        Both users here have a ``status_completed`` event, the row shape whose
        ``rating_id`` is NULL: if the new author join were hung off the LEFT
        JOIN to ``user_ratings`` it would drop *both* of them, and the type
        would silently lose every completion it has.
        """
        movie = await _make_movie(db, "ban-mixed-movie")
        for banned in (True, False):
            user_id = await _make_user(db, banned=banned)
            await _add_event(
                db,
                user_id=user_id,
                item_type="MOVIE",
                item_id=movie.id,
                event_type="status_completed",
                age=timedelta(minutes=5),
            )

        signal = await self._signal(db, "MOVIE")

        assert signal.total_gestures == 1
        assert signal.distinct_users == 1
        assert [item_id for item_id, _ in signal.scored] == [movie.id]

    async def test_a_banned_users_completion_does_not_resurrect_their_own_intent(self, db):
        """Where the two exclusions meet (issue #29, point 4).

        Contribution 2 drops a library row when the **same user** has a
        ``status_completed`` event in the window — that is the ``NOT EXISTS``
        of issue #30. A banned user's completion event no longer counts, so the
        question is whether the row it was suppressing should come back. It
        must not: the library row belongs to the same banned user and is
        excluded on its own account, before the ``NOT EXISTS`` is ever
        relevant. Both halves of the cycle leave with their owner.
        """
        movie = await _make_movie(db, "ban-cycle-movie")
        user_id = await _make_user(db, banned=True)
        await _add_event(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            event_type="status_completed",
            age=timedelta(minutes=5),
        )
        await _add_library_entry(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            status="dropped",
            age=timedelta(minutes=4),
        )

        signal = await self._signal(db, "MOVIE")

        assert signal.total_gestures == 0

    async def test_banned_activity_does_not_carry_a_type_over_the_threshold(self, client, db):
        """End to end: moderation reaches the front page, not just the lists.

        Enough banned gestures to clear both minimums several times over, and
        the type still falls back to the catalog order.
        """
        quiet = await _make_book(db, "ban-thr-quiet", rating_internal=5.0)
        pushed = await _make_book(db, "ban-thr-pushed", rating_internal=1.0)
        await _burst(
            db,
            item_type="BOOK",
            item_id=pushed.id,
            count=max(settings.TRENDING_MIN_ACTIVITY, settings.TRENDING_MIN_USERS) + 2,
            age=timedelta(minutes=5),
            banned=True,
        )

        slugs = _slugs((await client.get("/v1/trending?type=book")).json())

        assert slugs.index(quiet.slug) < slugs.index(pushed.slug)


# ---------------------------------------------------------------------------
# The threshold counts people, not gestures (issue #35)
# ---------------------------------------------------------------------------


class TestDistinctUserThreshold:
    """``TRENDING_MIN_ACTIVITY`` alone is a proxy for "there is a community
    here", and it is a good proxy only once the community exists. One account
    rating or shelving ``TRENDING_MIN_ACTIVITY`` *different* items crosses it
    by itself with entirely legitimate gestures, and then owns the whole type.

    So the local signal needs a second, independent condition:
    ``TRENDING_MIN_USERS`` distinct people behind those same de-duplicated,
    moderation-filtered gestures.
    """

    async def _signal(self, db, item_type: str):
        now = datetime.now(UTC)
        return await trending_repo.activity_scores(
            db,
            item_type=item_type,
            since=now - timedelta(days=7),
            now=now,
            half_life_seconds=42 * 3600,
            limit=20,
        )

    async def test_a_lone_user_with_enough_items_does_not_serve_the_ranking(self, client, db):
        """The issue itself: one person, one gesture per item, no community."""
        assert settings.TRENDING_MIN_USERS > 1
        quiet = await _make_movie(db, "min-users-quiet", rating_internal=5.0)
        user_id = await _make_user(db)
        touched = []
        for n in range(settings.TRENDING_MIN_ACTIVITY + 1):
            movie = await _make_movie(db, f"min-users-solo-{n}", rating_internal=1.0)
            touched.append(movie)
            await _add_library_entry(
                db,
                user_id=user_id,
                item_type="MOVIE",
                item_id=movie.id,
                status="want",
                age=timedelta(minutes=5),
            )

        signal = await self._signal(db, "MOVIE")
        slugs = _slugs((await client.get("/v1/trending?type=movie")).json())

        # The gesture count is comfortably over the old threshold: it is the
        # people count, and only it, that sends this back to the catalog.
        assert signal.total_gestures > settings.TRENDING_MIN_ACTIVITY
        assert signal.distinct_users == 1
        assert quiet.slug in slugs
        for movie in touched:
            assert slugs.index(quiet.slug) < slugs.index(movie.slug)

    async def test_enough_distinct_users_still_serve_the_local_ranking(self, client, db):
        """The other side of the same coin — the gate must not swallow real
        signal. Several different people on one item is exactly what trending
        exists to surface."""
        quiet = await _make_game(db, "min-users-quiet-game", rating_internal=5.0)
        busy = await _make_game(db, "min-users-busy-game", rating_internal=1.0)
        crowd = max(settings.TRENDING_MIN_ACTIVITY, settings.TRENDING_MIN_USERS)
        await _burst(db, item_type="GAME", item_id=busy.id, count=crowd, age=timedelta(minutes=5))

        signal = await self._signal(db, "GAME")
        slugs = _slugs((await client.get("/v1/trending?type=game")).json())

        assert signal.distinct_users == crowd
        assert slugs == [busy.slug]
        assert quiet.slug not in slugs

    async def test_distinct_users_counts_people_not_their_gestures(self, db):
        """Two gestures from one account are still one person — the counter is
        over the collapsed rows, per user, not per row."""
        movie = await _make_movie(db, "min-users-two-gestures-movie")
        user_id = await _make_user(db)
        rating = await _add_rating(
            db, user_id=user_id, item_type="MOVIE", item_id=movie.id, age=timedelta(minutes=5)
        )
        await _add_event(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            event_type="rating_created",
            age=timedelta(minutes=5),
            rating_id=rating.id,
        )
        await _add_event(
            db,
            user_id=user_id,
            item_type="MOVIE",
            item_id=movie.id,
            event_type="status_completed",
            age=timedelta(minutes=5),
        )

        signal = await self._signal(db, "MOVIE")

        assert signal.total_gestures == 2
        assert signal.distinct_users == 1

    async def test_banned_users_do_not_count_towards_the_minimum(self, db):
        """The two exclusions compose: the people counter runs over the same
        filtered rows as the score, so a banned crowd is not a crowd."""
        book = await _make_book(db, "min-users-banned-book")
        await _burst(db, item_type="BOOK", item_id=book.id, count=2, age=timedelta(minutes=5))
        await _burst(
            db,
            item_type="BOOK",
            item_id=book.id,
            count=5,
            age=timedelta(minutes=5),
            banned=True,
        )

        signal = await self._signal(db, "BOOK")

        assert signal.total_gestures == 2
        assert signal.distinct_users == 2

    async def test_distinct_users_are_counted_per_type_not_per_item(self, client, db):
        """Several pairs of different people, each pair on a different item.

        The counter has the same scope as ``total_gestures`` and as the
        threshold that reads it: the **type's** whole window, not one item.
        Correlating it by ``item_id`` would report 2 here — below
        ``TRENDING_MIN_USERS`` — and send a type with six active people back to
        the catalog. ``docs/api.md`` states the per-type reading; nothing
        pinned it until now, and every other test in this class uses either one
        item or one user, so none of them can tell the two apart.

        Two users per item is what makes the distinction bite (it has to be
        under the people minimum); the number of items is just what it takes to
        clear the gesture minimum at that rate.
        """
        assert 2 < settings.TRENDING_MIN_USERS, "a pair must be too few for the per-item reading"
        pairs = -(-settings.TRENDING_MIN_ACTIVITY // 2)
        quiet = await _make_book(db, "min-users-per-type-quiet", rating_internal=5.0)
        touched = []
        for n in range(pairs):
            book = await _make_book(db, f"min-users-per-type-{n}", rating_internal=1.0)
            touched.append(book)
            await _burst(db, item_type="BOOK", item_id=book.id, count=2, age=timedelta(minutes=5))

        signal = await self._signal(db, "BOOK")
        slugs = _slugs((await client.get("/v1/trending?type=book")).json())

        assert signal.distinct_users == 2 * pairs
        assert signal.total_gestures == 2 * pairs
        assert set(slugs) == {book.slug for book in touched}
        assert quiet.slug not in slugs

    async def test_min_users_is_configurable(self, client, db, monkeypatch):
        """Same knob shape as ``TRENDING_MIN_ACTIVITY``: an operator can move
        it without a code change, and it is evaluated per type."""
        from backlogg.core.cache import get_cache

        busy = await _make_series(db, "min-users-cfg-busy", rating_internal=1.0)
        quiet = await _make_series(db, "min-users-cfg-quiet", rating_internal=5.0)
        await _burst(
            db,
            item_type="SERIES",
            item_id=busy.id,
            count=settings.TRENDING_MIN_ACTIVITY,
            age=timedelta(minutes=5),
        )

        monkeypatch.setattr(settings, "TRENDING_MIN_USERS", 99)
        high = _slugs((await client.get("/v1/trending?type=series")).json())

        get_cache().clear()
        monkeypatch.setattr(settings, "TRENDING_MIN_USERS", 2)
        low = _slugs((await client.get("/v1/trending?type=series")).json())

        assert high.index(quiet.slug) < high.index(busy.slug)  # fallback order
        assert low == [busy.slug]  # local ranking


# ---------------------------------------------------------------------------
# The fallback runs no COUNT(*) it is going to throw away (issue #31)
# ---------------------------------------------------------------------------


class TestFallbackSkipsTheDiscardedCount:
    """The fallback reuses the catalog ``list_*`` functions for their canonical
    ``ORDER BY`` (feature 66) and never paginates, so the pagination total they
    compute is discarded — but the ``COUNT(*)`` still ran. Four per mix, eight
    when a type relaxes its empty release window.
    """

    async def _count_statements(self, db, monkeypatch, coro_factory):
        """Run ``coro_factory()`` recording every statement the session runs."""
        executed: list[str] = []
        original = db.execute

        async def spy(statement, *args, **kwargs):
            executed.append(str(statement))
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", spy)
        await coro_factory()
        monkeypatch.undo()
        return [sql for sql in executed if "count(" in sql.lower()]

    @pytest.mark.parametrize(
        ("item_type", "make"),
        [
            ("MOVIE", _make_movie),
            ("SERIES", _make_series),
            ("BOOK", _make_book),
            ("GAME", _make_game),
        ],
    )
    async def test_the_catalog_fallback_runs_no_count_query(self, db, monkeypatch, item_type, make):
        """All four branches, not just one.

        ``_list_recent_catalog`` has a separate call site per type, so there
        are four independent ``with_total=False`` to lose. Covering only movies
        and books let two of them regress in silence (found in review: removing
        the flag from the SERIES and GAME branches left the suite green).
        """
        await make(db, f"cnt-fallback-{item_type.lower()}", rating_internal=4.0)

        counts = await self._count_statements(
            db, monkeypatch, lambda: trending_service._fallback(db, item_type, "week", 20)
        )

        assert counts == []

    async def test_the_relaxed_second_pass_runs_no_count_query_either(self, db, monkeypatch):
        """The empty-window case is the one that pays twice."""
        await _make_book(db, "cnt-ancient-book", first_publish_date=date(1927, 1, 1))

        counts = await self._count_statements(
            db, monkeypatch, lambda: trending_service._fallback(db, "BOOK", "day", 20)
        )

        assert counts == []

    async def test_with_total_false_returns_none_not_zero_in_all_four(self, db):
        """``None`` means "not computed"; ``0`` would be a real, wrong answer —
        and the same answer in the four repositories, not four conventions."""
        await _make_movie(db, "cnt-none-movie")
        await _make_series(db, "cnt-none-series")
        await _make_book(db, "cnt-none-book")
        await _make_game(db, "cnt-none-game")

        _, movie_total = await movies_repo.list_movies(
            db, genre=None, sort=MovieSortEnum.rating_desc, page=1, limit=5, with_total=False
        )
        _, series_total = await series_repo.list_series(
            db, genre=None, sort=SeriesSortEnum.rating_desc, page=1, limit=5, with_total=False
        )
        _, book_total = await books_repo.list_books(
            db, genre=None, sort=BookSortEnum.rating_desc, page=1, limit=5, with_total=False
        )
        _, game_total = await games_repo.list_games(
            db, genre=None, sort=GameSortEnum.rating_desc, page=1, limit=5, with_total=False
        )

        assert (movie_total, series_total, book_total, game_total) == (None, None, None, None)

    async def test_the_paginating_callers_keep_their_total_by_default(self, db):
        """The default preserves the existing contract: every caller that
        paginates still gets a real count without asking for it."""
        await _make_movie(db, "cnt-default-movie")

        items, total = await movies_repo.list_movies(
            db, genre=None, sort=MovieSortEnum.rating_desc, page=1, limit=5
        )

        assert isinstance(total, int)
        assert total >= len(items) >= 1
