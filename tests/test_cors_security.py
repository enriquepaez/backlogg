"""Tests for CORS middleware and security headers (feature #22 — cors_and_security).

Acceptance criteria validated here:
  AC1  CORSMiddleware added to the FastAPI app
  AC2  CORS_ORIGINS env var (comma-separated) defines allowed origins
  AC3  Without CORS_ORIGINS, allows http://localhost:3000 and http://localhost:5173
  AC4  OPTIONS preflight requests return 200 with correct CORS headers
  AC5  Header X-Content-Type-Options: nosniff present in all responses
  AC6  Header X-Frame-Options: DENY present in all responses
  AC7  Header Referrer-Policy: strict-origin-when-cross-origin present
  AC8  Middleware tests verify headers in responses
"""

import importlib
import sys

from fastapi.testclient import TestClient

from backlogg.main import app

client = TestClient(app, raise_server_exceptions=True)

# ── Security headers ───────────────────────────────────────────────────────────


def test_security_headers_present():
    """AC5/AC6/AC7: Security headers present on every GET response."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


# ── CORS — allowed origins ─────────────────────────────────────────────────────


def test_cors_allowed_origin_localhost_3000():
    """AC1/AC3: GET /health with Origin: http://localhost:3000 returns CORS header."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allowed_origin_localhost_5173():
    """AC1/AC3: GET /health with Origin: http://localhost:5173 returns CORS header."""
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_disallowed_origin():
    """AC1: GET /health with an unknown origin does not return Access-Control-Allow-Origin."""
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200
    # FastAPI CORS middleware omits the header for disallowed origins
    assert "http://evil.example.com" not in (
        response.headers.get("access-control-allow-origin", "")
    )


# ── CORS — preflight ───────────────────────────────────────────────────────────


def test_cors_preflight_localhost_3000():
    """AC4: OPTIONS preflight from localhost:3000 returns 200 and CORS headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "GET" in response.headers.get("access-control-allow-methods", "")


def test_cors_preflight_localhost_5173():
    """AC4: OPTIONS preflight from localhost:5173 returns 200 and CORS headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ── CORS — default origins ─────────────────────────────────────────────────────


def test_cors_default_origins_are_localhost():
    """AC3: Without CORS_ORIGINS env var, both localhost ports are allowed.

    We test against the already-initialised 'app' instance which uses
    the default origins (no CORS_ORIGINS set during test run).
    """
    for origin in ("http://localhost:3000", "http://localhost:5173"):
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin, (
            f"Expected {origin} to be allowed, got: "
            f"{response.headers.get('access-control-allow-origin')}"
        )


def test_cors_custom_origins_via_env(monkeypatch):
    """AC2: When CORS_ORIGINS is set, only those origins are allowed."""
    custom_origin = "https://app.example.com"
    monkeypatch.setenv("CORS_ORIGINS", custom_origin)

    # Reload the module so middleware picks up the patched env var
    if "backlogg.main" in sys.modules:
        del sys.modules["backlogg.main"]
    mod = importlib.import_module("backlogg.main")
    custom_client = TestClient(mod.app)

    # Custom origin is allowed
    response = custom_client.get("/health", headers={"Origin": custom_origin})
    assert response.headers.get("access-control-allow-origin") == custom_origin

    # Default localhost is NOT allowed when CORS_ORIGINS overrides it
    response = custom_client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") != "http://localhost:3000"
