"""Tests for PATCH /v1/admin/{type}/{slug} (feature 49 — catalog_manual_edit).

Covers:
- 200 happy path: edited fields persisted + added to locked_fields.
- unlock_fields releases a field back to sync control (same request as an
  edit, or on its own).
- 422 for an unknown JSON key, a field that exists but is not editable for
  the given type, and an empty title.
- 404 for an unknown slug.
- 401 without X-API-Key (same gate as the rest of /v1/admin/*).
- Sync-job integration: a locked field survives the next nightly sync run
  untouched, while unlocked fields still sync normally.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.books import repository as books_repo
from backlogg.core.database import get_db
from backlogg.main import app
from backlogg.movies import repository as movies_repo
from backlogg.scheduler import jobs as sync_jobs
from backlogg.scheduler.repository import SeedTargetRow, upsert_seed_targets

_VALID_KEY = "test-admin-secret"


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the app + test DB, with a known admin X-API-Key."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


def _admin() -> dict:
    return {"X-API-Key": _VALID_KEY}


def _movie_data(slug: str, title: str = "Test Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test movie overview.",
        "release_date": None,
        "runtime": 120,
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
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Action", "slug": "action"}],
    }


async def _seed_movie(db, slug: str, title: str = "Test Movie"):
    return await movies_repo.upsert_movie(db, _movie_data(slug, title=title))


# ── Happy path ────────────────────────────────────────────────────────────────


async def test_edit_movie_returns_200_and_locks_fields(client, db):
    await _seed_movie(db, "edit-movie-happy")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-happy",
        headers=_admin(),
        json={"title": "Corrected Title", "poster_url": "https://example.com/p.jpg"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "movie"
    assert body["slug"] == "edit-movie-happy"
    assert body["title"] == "Corrected Title"
    assert body["poster_url"] == "https://example.com/p.jpg"
    assert set(body["locked_fields"]) == {"title", "poster_url"}
    # Non-relevant date fields for `movie` are always null in the response
    assert body["first_air_date"] is None
    assert body["first_publish_date"] is None


async def test_edit_movie_genres_by_name(client, db):
    await _seed_movie(db, "edit-movie-genres")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-genres",
        headers=_admin(),
        json={"genres": ["Science Fiction", "Adventure"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["genres"]) == {"Science Fiction", "Adventure"}
    assert "genres" in body["locked_fields"]


async def test_edit_movie_locked_fields_accumulate_across_requests(client, db):
    await _seed_movie(db, "edit-movie-accumulate")

    first = await client.patch(
        "/v1/admin/movie/edit-movie-accumulate", headers=_admin(), json={"title": "First Edit"}
    )
    assert set(first.json()["locked_fields"]) == {"title"}

    second = await client.patch(
        "/v1/admin/movie/edit-movie-accumulate",
        headers=_admin(),
        json={"poster_url": "https://example.com/p2.jpg"},
    )
    assert set(second.json()["locked_fields"]) == {"title", "poster_url"}


def _book_data(slug: str, title: str = "Test Book") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test book overview.",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Fiction", "slug": "fiction"}],
    }


async def test_edit_book_uses_first_publish_date(client, db):
    """Sanity check that the generic per-type dispatch also works for `book`."""
    await books_repo.upsert_book(db, _book_data("edit-book-happy"))

    response = await client.patch(
        "/v1/admin/book/edit-book-happy",
        headers=_admin(),
        json={"first_publish_date": "1999-03-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "book"
    assert body["first_publish_date"] == "1999-03-01"
    assert body["release_date"] is None
    assert body["first_air_date"] is None
    assert body["locked_fields"] == ["first_publish_date"]


async def test_edit_book_movie_only_field_returns_422(client, db):
    await books_repo.upsert_book(db, _book_data("edit-book-non-editable"))

    response = await client.patch(
        "/v1/admin/book/edit-book-non-editable",
        headers=_admin(),
        json={"release_date": "2020-01-01"},
    )
    assert response.status_code == 422


# ── unlock_fields ─────────────────────────────────────────────────────────────


async def test_unlock_fields_releases_a_field(client, db):
    await _seed_movie(db, "edit-movie-unlock")

    await client.patch(
        "/v1/admin/movie/edit-movie-unlock", headers=_admin(), json={"title": "Locked Title"}
    )

    response = await client.patch(
        "/v1/admin/movie/edit-movie-unlock",
        headers=_admin(),
        json={"unlock_fields": ["title"]},
    )

    assert response.status_code == 200
    assert response.json()["locked_fields"] == []
    # The already-persisted edit is not reverted, only unlocked
    assert response.json()["title"] == "Locked Title"


async def test_unlock_fields_same_request_as_edit_ends_unlocked(client, db):
    """A field present in both the edit payload and unlock_fields ends up unlocked."""
    await _seed_movie(db, "edit-movie-unlock-same-request")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-unlock-same-request",
        headers=_admin(),
        json={"title": "Edited And Unlocked", "unlock_fields": ["title"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Edited And Unlocked"
    assert "title" not in body["locked_fields"]


# ── Validation ────────────────────────────────────────────────────────────────


async def test_edit_movie_unknown_field_returns_422(client, db):
    await _seed_movie(db, "edit-movie-unknown-field")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-unknown-field",
        headers=_admin(),
        json={"not_a_real_field": "value"},
    )
    assert response.status_code == 422


async def test_edit_movie_non_editable_field_for_type_returns_422(client, db):
    """first_air_date is a series-only field, not editable for a movie."""
    await _seed_movie(db, "edit-movie-non-editable")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-non-editable",
        headers=_admin(),
        json={"first_air_date": "2020-01-01"},
    )
    assert response.status_code == 422


async def test_unlock_non_editable_field_for_type_returns_422(client, db):
    await _seed_movie(db, "edit-movie-unlock-non-editable")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-unlock-non-editable",
        headers=_admin(),
        json={"unlock_fields": ["first_air_date"]},
    )
    assert response.status_code == 422


async def test_edit_movie_empty_title_returns_422(client, db):
    await _seed_movie(db, "edit-movie-empty-title")

    response = await client.patch(
        "/v1/admin/movie/edit-movie-empty-title", headers=_admin(), json={"title": "   "}
    )
    assert response.status_code == 422


# ── 404 ───────────────────────────────────────────────────────────────────────


async def test_edit_movie_unknown_slug_returns_404(client, db):
    response = await client.patch(
        "/v1/admin/movie/slug-that-does-not-exist-9999",
        headers=_admin(),
        json={"title": "Whatever"},
    )
    assert response.status_code == 404


# ── Auth ──────────────────────────────────────────────────────────────────────


async def test_edit_movie_without_api_key_returns_401(client, db):
    await _seed_movie(db, "edit-movie-no-key")

    response = await client.patch("/v1/admin/movie/edit-movie-no-key", json={"title": "Whatever"})
    assert response.status_code == 401


# ── Sync-job integration: locked field survives the next sync ────────────────


async def test_locked_field_survives_next_sync(db):
    """A field locked via the admin edit is untouched by the next sync_movies run.

    Unlocked fields (e.g. runtime) still sync normally for the same item.
    """
    await _seed_movie(db, "locked-survives-sync", title="Admin Corrected Title")
    movie = await movies_repo.get_movie_by_slug(db, "locked-survives-sync")
    movie.locked_fields = ["title"]
    await db.flush()

    # movie_to_dict is mocked directly (rather than relying on the real TMDB
    # slugify+year logic) so the sync's proposed slug matches the already
    # seeded item, exercising the ON CONFLICT DO UPDATE path deterministically.
    synced_movie_data = {
        "title": "TMDB Synced Title",
        "original_title": "TMDB Synced Title",
        "slug": "locked-survives-sync",
        "overview": "Synced overview.",
        "release_date": date(2021, 5, 1),
        "runtime": 150,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "rating_external": 8.0,
        "rating_count_external": 200,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }

    # The slice comes from the seed target list since feature 86.
    await upsert_seed_targets(
        db, [SeedTargetRow("MOVIE", "TMDB", "555001", vote_count=200, release_year=2021)]
    )
    await db.commit()

    with (
        patch.object(
            sync_jobs._tmdb_movies,
            "get_movie_detail",
            new_callable=AsyncMock,
            return_value={"id": 555001, "credits": {"cast": [], "crew": []}},
        ),
        patch.object(
            sync_jobs._tmdb_movies,
            "movie_to_dict",
            return_value=dict(synced_movie_data),
        ),
        patch.object(sync_jobs, "_refresh_catalog_search", new_callable=AsyncMock),
        patch("backlogg.scheduler.jobs.async_session_factory") as mock_factory,
    ):
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_cm

        result = await sync_jobs.sync_movies(slice_size=5)

    assert result["synced"] == 1

    refreshed = await movies_repo.get_movie_by_slug(db, "locked-survives-sync")
    # title is locked -> the sync's proposed value must NOT win
    assert refreshed.title == "Admin Corrected Title"
    # runtime is not locked -> synced normally
    assert refreshed.runtime == 150
