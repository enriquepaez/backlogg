"""Tests for response caching (feature 40).

Covers the two acceptance criteria that need explicit verification:

* Detail reads support ``ETag`` + ``If-None-Match`` → ``304``, and emit the
  right ``Cache-Control`` (public for anonymous, private for authenticated so a
  user-specific ``viewer_status`` body never lands in a shared cache). Listings
  are ``public``; per-user reads (``/users/me``, ``/feed``) are ``private,
  no-store``.
* The in-process TTL cache backing ``/genres`` and ``/trending`` serves hits
  within the TTL and refreshes once the TTL elapses (no stale data).
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.core.cache import InMemoryTTLCache
from backlogg.genres import service as genres_service
from backlogg.main import app
from backlogg.movies import repository as movies_repo


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


def _make_movie_dict(slug: str) -> dict:
    return {
        "title": "Cached Movie",
        "original_title": "Cached Movie",
        "slug": slug,
        "overview": "A movie used to exercise response caching.",
        "release_date": date(2001, 5, 10),
        "runtime": 120,
        "original_language": "en",
        "poster_url": "https://image.tmdb.org/t/p/w500/cached.jpg",
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": 7.5,
        "rating_count_external": 100,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Drama", "slug": "drama-cache-test"}],
    }


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


async def _register_and_login(client, username: str) -> str:
    await client.post(
        "/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "s3cret-pass"},
    )
    login = await client.post(
        "/v1/auth/login", json={"username": username, "password": "s3cret-pass"}
    )
    return login.json()["access_token"]


# ── Detail: Cache-Control + ETag + 304 ───────────────────────────────────────


async def test_detail_anonymous_is_public_and_has_etag(client, db):
    await movies_repo.upsert_movie(db, _make_movie_dict("cache-anon-movie-2001"))

    response = await client.get("/v1/movies/cache-anon-movie-2001")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.headers.get("etag")
    assert response.headers.get("vary") == "Authorization"


async def test_detail_if_none_match_returns_304(client, db):
    await movies_repo.upsert_movie(db, _make_movie_dict("cache-304-movie-2001"))

    first = await client.get("/v1/movies/cache-304-movie-2001")
    etag = first.headers["etag"]

    second = await client.get("/v1/movies/cache-304-movie-2001", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""


async def test_detail_stale_etag_returns_full_body(client, db):
    await movies_repo.upsert_movie(db, _make_movie_dict("cache-stale-etag-2001"))

    response = await client.get(
        "/v1/movies/cache-stale-etag-2001", headers={"If-None-Match": '"not-the-current-etag"'}
    )
    assert response.status_code == 200
    assert response.json()["slug"] == "cache-stale-etag-2001"


async def test_detail_authenticated_is_private_not_shared(client, db):
    await movies_repo.upsert_movie(db, _make_movie_dict("cache-auth-movie-2001"))
    token = await _register_and_login(client, "cache-detail-user")

    response = await client.get(
        "/v1/movies/cache-auth-movie-2001", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    # Authenticated detail includes viewer_status → never shared-cacheable.
    cache_control = response.headers["cache-control"]
    assert "private" in cache_control
    assert "public" not in cache_control
    assert response.headers.get("vary") == "Authorization"
    assert response.headers.get("etag")


async def test_detail_authenticated_supports_304(client, db):
    await movies_repo.upsert_movie(db, _make_movie_dict("cache-auth-304-2001"))
    token = await _register_and_login(client, "cache-detail-304-user")
    auth = {"Authorization": f"Bearer {token}"}

    first = await client.get("/v1/movies/cache-auth-304-2001", headers=auth)
    etag = first.headers["etag"]

    second = await client.get(
        "/v1/movies/cache-auth-304-2001", headers={**auth, "If-None-Match": etag}
    )
    assert second.status_code == 304


# ── Listings: public Cache-Control ────────────────────────────────────────────


async def test_movies_listing_is_public(client, db):
    response = await client.get("/v1/movies")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_genres_listing_is_public(client, db):
    response = await client.get("/v1/genres")
    assert response.status_code == 200
    # /genres advertises its in-process cache TTL.
    assert response.headers["cache-control"] == "public, max-age=300"


async def test_trending_listing_is_public(client, db):
    with (
        patch(
            "backlogg.trending.service._movies_tmdb.get_trending_movies",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "backlogg.trending.service._series_tmdb.get_trending_series",
            new=AsyncMock(return_value=[]),
        ),
    ):
        response = await client.get("/v1/trending")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=900"


# ── Per-user reads: never shared-cacheable ────────────────────────────────────


async def test_users_me_is_private_no_store(client, db):
    token = await _register_and_login(client, "cache-me-user")

    response = await client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers


async def test_feed_is_private_no_store(client, db):
    token = await _register_and_login(client, "cache-feed-user")

    response = await client.get("/v1/feed", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


# ── In-process TTL cache wired into the services ──────────────────────────────


async def test_genres_service_serves_hit_within_ttl(db):
    """A second call within the TTL is a cache hit — the repository is not hit."""
    with patch.object(
        genres_service.repo, "list_genres", new=AsyncMock(return_value=[])
    ) as repo_mock:
        first = await genres_service.list_genres(db, item_type=None)
        second = await genres_service.list_genres(db, item_type=None)

    assert first == second
    repo_mock.assert_called_once()


async def test_genres_service_refreshes_after_ttl(db, monkeypatch):
    """Past the TTL the cached value is dropped and the repository is hit again."""
    clock = _FakeClock()
    monkeypatch.setattr("backlogg.core.cache._cache", InMemoryTTLCache(now=clock))

    with patch.object(
        genres_service.repo, "list_genres", new=AsyncMock(return_value=[])
    ) as repo_mock:
        await genres_service.list_genres(db, item_type=None)
        # Within TTL → still a hit.
        clock.advance(1)
        await genres_service.list_genres(db, item_type=None)
        assert repo_mock.call_count == 1

        # Past the configured genres TTL → miss, recomputed from the repository.
        from backlogg.core.config import settings

        clock.advance(settings.CACHE_TTL_GENRES + 1)
        await genres_service.list_genres(db, item_type=None)
        assert repo_mock.call_count == 2
