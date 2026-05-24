"""Tests for the IGDB client adapter — token renewal and data mapping."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backlogg.games.adapters.igdb import IGDBClient


@pytest.fixture
def client():
    return IGDBClient()


async def test_ensure_token_fetches_when_none(client):
    """Token is fetched when not yet set."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok123", "expires_in": 3600}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        await client._ensure_token()

    assert client._access_token == "tok123"
    assert client._token_expires_at > 0


async def test_ensure_token_renews_when_expired(client):
    """Token is renewed when it has expired."""
    client._access_token = "old-token"
    client._token_expires_at = 0.0  # already expired

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "new-token", "expires_in": 3600}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        await client._ensure_token()

    assert client._access_token == "new-token"


async def test_ensure_token_skips_when_valid(client):
    """Token is NOT renewed when it is still valid."""
    import time

    client._access_token = "valid-token"
    client._token_expires_at = time.time() + 3600  # valid for 1 hour

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        await client._ensure_token()

    mock_post.assert_not_called()
    assert client._access_token == "valid-token"


def test_game_to_dict_main_game(client):
    """game_to_dict converts a IGDB raw dict correctly."""
    raw = {
        "id": 1942,
        "name": "The Witcher 3: Wild Hunt",
        "slug": "the-witcher-3-wild-hunt",
        "summary": "An epic RPG set in a fantasy world.",
        "cover": {"image_id": "co1wyy"},
        "first_release_date": 1431993600,  # 2015-05-19 UTC
        "rating": 92.5,
        "rating_count": 5432,
        "game_type": 0,
        "genres": [{"name": "Role-playing (RPG)", "slug": "role-playing-rpg"}],
        "platforms": [{"name": "PC (Microsoft Windows)", "slug": "win"}],
        "involved_companies": [
            {
                "company": {"name": "CD Projekt Red", "slug": "cd-projekt-red"},
                "developer": True,
                "publisher": False,
            }
        ],
    }

    result = client.game_to_dict(raw)

    assert result["title"] == "The Witcher 3: Wild Hunt"
    assert result["slug"] == "the-witcher-3-wild-hunt"
    assert result["game_type"] == "MAIN_GAME"
    assert result["release_date"] == date(2015, 5, 19)
    assert result["rating_external"] == 9.2  # 92.5 / 10 rounded to 1 decimal
    assert result["rating_count_external"] == 5432
    assert result["poster_url"] == (
        "https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg"
    )
    assert result["overview"] == "An epic RPG set in a fantasy world."
    assert len(result["genres"]) == 1
    assert result["genres"][0]["slug"] == "role-playing-rpg"
    assert len(result["platforms"]) == 1
    assert result["platforms"][0]["slug"] == "win"
    assert len(result["companies"]) == 1
    assert result["companies"][0]["role"] == "DEVELOPER"


def test_game_to_dict_no_cover(client):
    """game_to_dict handles missing cover gracefully."""
    raw = {
        "id": 1,
        "name": "Test Game",
        "slug": "test-game",
        "game_type": 0,
    }
    result = client.game_to_dict(raw)
    assert result["poster_url"] is None
    assert result["release_date"] is None
    assert result["rating_external"] is None


def test_game_to_dict_dlc_type(client):
    """game_to_dict maps game_type=1 to DLC_ADDON."""
    raw = {
        "id": 2,
        "name": "Some DLC",
        "slug": "some-dlc",
        "game_type": 1,
    }
    result = client.game_to_dict(raw)
    assert result["game_type"] == "DLC_ADDON"
