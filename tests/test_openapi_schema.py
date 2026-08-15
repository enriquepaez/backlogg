"""Tests for the enriched OpenAPI schema (feature #41 — openapi_polish).

Acceptance criteria validated here:
  AC1  Routers declare summary/description per operation
  AC2  Key response schemas include examples
  AC3  The FastAPI instance declares title, version and description
  AC4  GET /openapi.json validates as OpenAPI 3.x and reflects tags and examples
  AC6  Tests verify presence of tags and examples in the generated schema
"""

from fastapi.testclient import TestClient

from backlogg.main import app

client = TestClient(app)


def _schema() -> dict:
    return app.openapi()


# ── OpenAPI version + app metadata ─────────────────────────────────────────────


def test_openapi_is_3_x():
    """AC4: the generated document declares an OpenAPI 3.x version."""
    schema = _schema()
    assert schema["openapi"].startswith("3.")


def test_openapi_json_endpoint_serves_schema():
    """AC4: GET /openapi.json serves the same 3.x document."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert body["openapi"].startswith("3.")


def test_info_has_title_version_and_description():
    """AC3: info block declares title, version (0.1.0) and a non-empty description."""
    info = _schema()["info"]
    assert info["title"] == "Backlogg API"
    assert info["version"] == "0.1.0"
    assert isinstance(info.get("description"), str)
    assert info["description"].strip() != ""


# ── Tags ───────────────────────────────────────────────────────────────────────


def test_domain_tags_present_with_descriptions():
    """AC6: expected domain tags appear at top level with non-empty descriptions."""
    tags = {t["name"]: t for t in _schema().get("tags", [])}
    expected = [
        "movies",
        "series",
        "books",
        "games",
        "people",
        "search",
        "admin",
        "genres",
        "trending",
        "auth",
        "users",
        "ratings",
        "follows",
        "feed",
        "library",
        "notifications",
        "recommendations",
        "metrics",
    ]
    for name in expected:
        assert name in tags, f"missing tag: {name}"
        assert tags[name].get("description", "").strip() != "", f"tag {name} has no description"


# ── Operation summaries ────────────────────────────────────────────────────────


def test_key_operations_have_summary():
    """AC1: several key operations expose a non-empty summary."""
    paths = _schema()["paths"]
    checks = [
        ("/v1/movies/{slug}", "get"),
        ("/v1/auth/login", "post"),
        ("/v1/feed", "get"),
        ("/v1/search", "get"),
        ("/v1/recommendations", "get"),
        ("/v1/notifications", "get"),
    ]
    for path, method in checks:
        assert path in paths, f"missing path: {path}"
        op = paths[path][method]
        assert op.get("summary", "").strip() != "", f"{method.upper()} {path} lacks a summary"


# ── Response schema examples ───────────────────────────────────────────────────


def _schema_has_example(component: dict) -> bool:
    return "example" in component or "examples" in component


def test_response_schemas_expose_examples():
    """AC2: at least one key response schema exposes an example in components."""
    schemas = _schema()["components"]["schemas"]
    keyed = [
        "MovieOut",
        "SearchResponse",
        "GenreListOut",
        "TrendingOut",
        "FeedListOut",
        "LibraryListOut",
        "NotificationListOut",
        "RecommendationsOut",
    ]
    present = [name for name in keyed if name in schemas]
    assert present, "none of the expected response schemas are in the components"
    with_example = [name for name in present if _schema_has_example(schemas[name])]
    assert with_example, f"no example found on any of: {present}"
