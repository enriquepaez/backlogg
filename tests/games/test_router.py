from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.games import repository as repo
from backlogg.games import service
from backlogg.main import app


def _make_game_dict(slug: str = "doom-1993") -> dict:
    return {
        "title": "DOOM",
        "original_title": None,
        "slug": slug,
        "overview": "A classic FPS.",
        "release_date": date(1993, 12, 10),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/doom.jpg",
        "backdrop_url": None,
        "rating_external": 9.0,
        "rating_count_external": 3000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Shooter", "slug": "shooter"}],
        "platforms": [{"name": "PC (Microsoft Windows)", "slug": "win"}],
        "companies": [],
    }


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


async def test_get_game_returns_200(client, db):
    """GET /games/{slug} returns 200 with correct fields for a seeded game."""
    await repo.upsert_game(db, _make_game_dict("doom-1993-endpoint"))

    response = await client.get("/games/doom-1993-endpoint")
    assert response.status_code == 200

    body = response.json()
    assert body["slug"] == "doom-1993-endpoint"
    assert body["title"] == "DOOM"
    assert body["game_type"] == "MAIN_GAME"
    assert body["release_date"] == "1993-12-10"
    assert len(body["genres"]) == 1
    assert body["genres"][0]["name"] == "Shooter"
    assert len(body["platforms"]) == 1
    assert body["platforms"][0]["slug"] == "win"


async def test_get_game_returns_404(client, db):
    """GET /games/{slug} returns 404 when not in DB and IGDB has nothing."""
    with patch.object(
        service._igdb_client, "get_game_by_slug", new_callable=AsyncMock, return_value=None
    ):
        response = await client.get("/games/nonexistent-game-slug-404-test")

    assert response.status_code == 404


async def test_get_game_fallback_endpoint(client, db):
    """GET /games/{slug} fetches from IGDB when not in DB and persists it."""
    game_dict = _make_game_dict("quake-1996-endpoint")
    raw_igdb = {"id": 99, "slug": "quake-1996-endpoint"}

    with (
        patch.object(
            service._igdb_client,
            "get_game_by_slug",
            new_callable=AsyncMock,
            return_value=raw_igdb,
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=game_dict,
        ),
    ):
        response = await client.get("/games/quake-1996-endpoint")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "DOOM"
    assert body["slug"] == "quake-1996-endpoint"
