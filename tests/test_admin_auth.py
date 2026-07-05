"""Tests for admin endpoint authentication (feature 18 — admin_api_key).

Acceptance criteria validated here:
  AC1  POST /admin/sync/{type} without X-API-Key → 401
  AC2  POST /admin/sync/{type} with wrong X-API-Key → 401
  AC3  POST /admin/sync/{type} with correct X-API-Key → 200
  AC4  GET /admin/stats protected with same logic
  AC5  ADMIN_API_KEY not set → 503
  AC6  Key value does not appear in error response bodies
"""

from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.main import app

_VALID_KEY = "super-secret-admin-key"
_WRONG_KEY = "wrong-key"

_SYNC_RESULT = {"synced": 1, "errors": 0, "offset": 0, "duration_s": 0.1}


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_key():
    """AsyncClient where ADMIN_API_KEY is configured to _VALID_KEY."""
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = _VALID_KEY
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def client_no_env_key():
    """AsyncClient where ADMIN_API_KEY is not configured (empty string)."""
    with patch("backlogg.admin.auth.settings") as mock_settings:
        mock_settings.ADMIN_API_KEY = ""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


# ── POST /admin/sync/{type} ────────────────────────────────────────────────────


async def test_sync_without_api_key_returns_401(client_with_key):
    """AC1: POST /admin/sync/movie without X-API-Key returns 401."""
    response = await client_with_key.post("/admin/sync/movie")
    assert response.status_code == 401


async def test_sync_with_wrong_api_key_returns_401(client_with_key):
    """AC2: POST /admin/sync/movie with wrong X-API-Key returns 401."""
    response = await client_with_key.post("/admin/sync/movie", headers={"X-API-Key": _WRONG_KEY})
    assert response.status_code == 401


async def test_sync_with_correct_api_key_returns_200(client_with_key):
    """AC3: POST /admin/sync/movie with correct X-API-Key returns 200."""
    mock_handler = AsyncMock(return_value=_SYNC_RESULT)
    with patch.dict("backlogg.admin.router._SYNC_HANDLERS", {"movie": mock_handler}):
        response = await client_with_key.post(
            "/admin/sync/movie", headers={"X-API-Key": _VALID_KEY}
        )
    assert response.status_code == 200


async def test_sync_key_not_in_401_body(client_with_key):
    """AC6: The configured key value must not appear in the 401 error response."""
    response = await client_with_key.post("/admin/sync/movie", headers={"X-API-Key": _WRONG_KEY})
    assert response.status_code == 401
    assert _VALID_KEY not in response.text
    assert _WRONG_KEY not in response.text


async def test_sync_no_env_key_returns_503(client_no_env_key):
    """AC5: When ADMIN_API_KEY is not set, POST /admin/sync returns 503."""
    response = await client_no_env_key.post("/admin/sync/movie", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 503


async def test_sync_no_env_key_503_body_has_no_key(client_no_env_key):
    """AC6: The 503 response body must not expose any key value."""
    response = await client_no_env_key.post("/admin/sync/movie", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 503
    assert _VALID_KEY not in response.text


# ── GET /admin/stats ───────────────────────────────────────────────────────────


async def test_stats_without_api_key_returns_401(client_with_key):
    """AC4: GET /admin/stats without X-API-Key returns 401."""
    response = await client_with_key.get("/admin/stats")
    assert response.status_code == 401


async def test_stats_with_wrong_api_key_returns_401(client_with_key):
    """AC4: GET /admin/stats with wrong X-API-Key returns 401."""
    response = await client_with_key.get("/admin/stats", headers={"X-API-Key": _WRONG_KEY})
    assert response.status_code == 401


async def test_stats_with_correct_api_key_returns_200(client_with_key):
    """AC4: GET /admin/stats with correct X-API-Key returns 200."""
    response = await client_with_key.get("/admin/stats", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 200


async def test_stats_no_env_key_returns_503(client_no_env_key):
    """AC5: When ADMIN_API_KEY is not set, GET /admin/stats returns 503."""
    response = await client_no_env_key.get("/admin/stats", headers={"X-API-Key": _VALID_KEY})
    assert response.status_code == 503


async def test_stats_key_not_in_401_body(client_with_key):
    """AC6: The configured key value must not appear in the 401 error response."""
    response = await client_with_key.get("/admin/stats", headers={"X-API-Key": _WRONG_KEY})
    assert response.status_code == 401
    assert _VALID_KEY not in response.text
    assert _WRONG_KEY not in response.text
