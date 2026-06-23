from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.games import repository as repo
from backlogg.games import service


def _make_raw_igdb() -> dict:
    return {
        "id": 1942,
        "name": "The Witcher 3: Wild Hunt",
        "slug": "the-witcher-3-wild-hunt",
        "summary": "An open world RPG.",
        "cover": {"image_id": "co1wyy"},
        "first_release_date": 1431993600,  # 2015-05-19 UTC
        "rating": 92.5,
        "rating_count": 5432,
        "game_type": 0,
        "genres": [
            {"name": "Role-playing (RPG)", "slug": "role-playing-rpg"},
        ],
        "platforms": [
            {"name": "PC (Microsoft Windows)", "slug": "win"},
        ],
        "involved_companies": [
            {
                "company": {"name": "CD Projekt Red", "slug": "cd-projekt-red"},
                "developer": True,
                "publisher": False,
            }
        ],
    }


def _make_game_dict() -> dict:
    return {
        "title": "The Witcher 3: Wild Hunt",
        "original_title": None,
        "slug": "the-witcher-3-wild-hunt",
        "overview": "An open world RPG.",
        "release_date": date(2015, 5, 19),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg",
        "backdrop_url": None,
        "rating_external": 9.2,
        "rating_count_external": 5432,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Role-playing (RPG)", "slug": "role-playing-rpg"}],
        "platforms": [{"name": "PC (Microsoft Windows)", "slug": "win"}],
        "companies": [{"name": "CD Projekt Red", "slug": "cd-projekt-red", "role": "DEVELOPER"}],
    }


async def test_get_game_found_in_db(db):
    """When game exists in DB, service returns it without calling IGDB."""
    await repo.upsert_game(db, _make_game_dict())

    with patch.object(service._igdb_client, "get_game_by_slug", new_callable=AsyncMock) as mock_get:
        result = await service.get_game(db, "the-witcher-3-wild-hunt")

    assert result.slug == "the-witcher-3-wild-hunt"
    mock_get.assert_not_called()


async def test_get_game_fallback_to_igdb(db):
    """When game is not in DB, service calls IGDB, persists and returns it."""
    raw = _make_raw_igdb()

    with (
        patch.object(
            service._igdb_client,
            "get_game_by_slug",
            new_callable=AsyncMock,
            return_value=raw,
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=_make_game_dict(),
        ),
    ):
        result = await service.get_game(db, "the-witcher-3-wild-hunt")

    assert result.title == "The Witcher 3: Wild Hunt"
    assert result.slug == "the-witcher-3-wild-hunt"

    # Verify persisted in DB
    persisted = await repo.get_game_by_slug(db, "the-witcher-3-wild-hunt")
    assert persisted is not None


async def test_get_game_not_found_anywhere(db):
    """When IGDB returns None for both slug and search, service raises HTTP 404."""
    with (
        patch.object(
            service._igdb_client, "get_game_by_slug", new_callable=AsyncMock, return_value=None
        ),
        patch.object(service._igdb_client, "search_games", new_callable=AsyncMock, return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_game(db, "this-game-does-not-exist-9999")

    assert exc_info.value.status_code == 404


async def test_get_game_title_search_fallback(db):
    """When get_game_by_slug returns None, search_games fallback is used."""
    raw = _make_raw_igdb()
    game_dict = _make_game_dict()

    with (
        patch.object(
            service._igdb_client, "get_game_by_slug", new_callable=AsyncMock, return_value=None
        ),
        patch.object(
            service._igdb_client,
            "search_games",
            new_callable=AsyncMock,
            return_value=[raw],
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=game_dict,
        ),
    ):
        result = await service.get_game(db, "the-witcher-3-wild-hunt-2015")

    assert result.title == "The Witcher 3: Wild Hunt"

    # Verify the game was persisted using the IGDB slug from game_to_dict
    persisted = await repo.get_game_by_slug(db, "the-witcher-3-wild-hunt")
    assert persisted is not None
