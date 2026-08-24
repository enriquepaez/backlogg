"""Tests for the IGDB client adapter — token renewal and data mapping."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


async def test_get_game_by_slug_requests_similar_games_field(client):
    """The POST /games detail query includes similar_games.* alongside the usual fields."""
    import time

    client._access_token = "valid-token"
    client._token_expires_at = time.time() + 3600  # skip token renewal

    mock_response = MagicMock()
    mock_response.json.return_value = [{"id": 1, "name": "Fake Game", "slug": "fake-game"}]
    mock_response.raise_for_status = MagicMock()

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        await client.get_game_by_slug("fake-game")

    _, kwargs = mock_post.call_args
    body = kwargs["content"]
    assert "similar_games.*" in body
    # Existing fields are still requested alongside it
    assert "cover.*" in body
    assert "genres.name,genres.slug" in body


async def test_search_games_forwards_offset_param(client):
    """search_games includes an `offset N;` clause in the IGDB query body (Issue #14)."""
    import time

    client._access_token = "valid-token"
    client._token_expires_at = time.time() + 3600  # skip token renewal

    mock_response = MagicMock()
    mock_response.json.return_value = [{"id": 1, "name": "Fake Game", "slug": "fake-game"}]
    mock_response.raise_for_status = MagicMock()

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        results = await client.search_games("fake game", limit=20, offset=40)

    _, kwargs = mock_post.call_args
    body = kwargs["content"]
    assert "limit 20;" in body
    assert "offset 40;" in body
    assert results == [{"id": 1, "name": "Fake Game", "slug": "fake-game"}]


async def test_search_games_retries_on_5xx_then_succeeds(client):
    """search_games is retried via tenacity on a transient 5xx (Issue #14)."""
    import time

    client._access_token = "valid-token"
    client._token_expires_at = time.time() + 3600  # skip token renewal

    call_count = 0

    def _mock_response(status_code: int, json_data=None):
        response = MagicMock()
        response.status_code = status_code
        if json_data is not None:
            response.json = MagicMock(return_value=json_data)
        if status_code >= 400:
            response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    f"HTTP {status_code}", request=MagicMock(), response=response
                )
            )
        else:
            response.raise_for_status = MagicMock()
        return response

    async def fake_post(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_response(500)
        return _mock_response(200, [{"id": 2, "name": "Retried Game"}])

    with (
        patch("httpx.AsyncClient.post", new=fake_post),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        results = await client.search_games("retry game")

    assert results == [{"id": 2, "name": "Retried Game"}]
    assert call_count == 2


async def test_search_games_non_retryable_4xx_raises_immediately(client):
    """A non-retryable 4xx from IGDB must raise without retry (Issue #14)."""
    import time

    client._access_token = "valid-token"
    client._token_expires_at = time.time() + 3600  # skip token renewal

    call_count = 0

    def _mock_response(status_code: int):
        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=response
            )
        )
        return response

    async def fake_post(*args, **kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _mock_response(400)

    with (
        patch("httpx.AsyncClient.post", new=fake_post),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_games("bad query")

    assert call_count == 1
    mock_sleep.assert_not_awaited()


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
