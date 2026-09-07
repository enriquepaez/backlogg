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
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backlogg.books import repository as books_repo
from backlogg.core.config import settings
from backlogg.feed.models import ActivityEvent
from backlogg.feed.repository import create_rating_event, create_status_completed_event
from backlogg.games import repository as games_repo
from backlogg.library.models import LibraryEntry
from backlogg.library.repository import upsert_library_entry
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.ratings.models import UserRating
from backlogg.ratings.repository import upsert_rating
from backlogg.series import repository as series_repo
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


async def _make_user(db, prefix: str = "trend"):
    username = f"{prefix}-user-{next(_seq)}"
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
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


async def _burst(db, *, item_type, item_id, count, age, status="want"):
    """``count`` distinct users adding the item to their backlog, all ``age`` old."""
    for _ in range(count):
        user_id = await _make_user(db)
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

        total, scored = await trending_repo.activity_scores(
            db,
            item_type="SERIES",
            since=datetime.now(UTC) - timedelta(days=7),
            now=datetime.now(UTC),
            half_life_seconds=42 * 3600,
            limit=20,
        )

        assert total == 0
        assert scored == []

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

        _, fresh_scores = await trending_repo.activity_scores(
            db,
            item_type="BOOK",
            since=now - timedelta(days=7),
            now=now,
            half_life_seconds=half_life.total_seconds(),
            limit=20,
        )
        _, aged_scores = await trending_repo.activity_scores(
            db,
            item_type="BOOK",
            since=now - timedelta(days=7),
            now=now + half_life,
            half_life_seconds=half_life.total_seconds(),
            limit=20,
        )

        assert aged_scores[0][1] == pytest.approx(fresh_scores[0][1] / 2, rel=1e-6)


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
        total, _ = await trending_repo.activity_scores(
            db,
            item_type=item_type,
            since=datetime.now(UTC) - timedelta(days=7),
            now=datetime.now(UTC),
            half_life_seconds=42 * 3600,
            limit=20,
        )
        return total

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
