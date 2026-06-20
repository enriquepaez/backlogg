# impl_18 — admin_api_key

## Files created

- `backlogg/admin/auth.py` — FastAPI dependency `verify_api_key`
- `tests/test_admin_auth.py` — 11 auth-specific tests covering all acceptance criteria

## Files modified

- `backlogg/core/config.py` — added `ADMIN_API_KEY: str = ""` to Settings
- `backlogg/admin/router.py` — injected `verify_api_key` at router level via `dependencies=[Depends(verify_api_key)]`; updated module docstring
- `tests/test_admin_sync.py` — updated `client` fixture to patch `settings.ADMIN_API_KEY` and added `X-API-Key` header to all endpoint calls
- `tests/test_admin_stats.py` — same fixture/header update
- `.env.example` — documented `ADMIN_API_KEY=` variable

## What was implemented and why

### `backlogg/admin/auth.py`

Created a standalone `verify_api_key` async dependency. It reads `settings.ADMIN_API_KEY`:
- If the setting is empty (not configured) → raises HTTP 503. This signals misconfiguration, not an auth failure.
- If the `X-API-Key` header is missing or does not exactly match the configured key → raises HTTP 401.
- The error response messages are generic ("not configured", "Invalid or missing") and never echo the actual key value, satisfying AC6.

`Header(default="")` is used instead of `Header(...)` so that a missing header produces an empty string rather than a 422 validation error — giving a consistent 401 for both missing and wrong key cases.

### Router injection strategy

The dependency is injected at the router level via `APIRouter(..., dependencies=[Depends(verify_api_key)])` rather than on each individual endpoint. This means all current and any future endpoints added to this router are automatically protected without having to remember to add the dependency manually.

### Test approach

- `client_with_key` fixture: patches `backlogg.admin.auth.settings` with `ADMIN_API_KEY = "super-secret-admin-key"` so the endpoint is armed.
- `client_no_env_key` fixture: patches with `ADMIN_API_KEY = ""` to exercise the 503 path.
- All existing tests in `test_admin_sync.py` and `test_admin_stats.py` were updated to patch the settings the same way and include `X-API-Key` headers, preserving all previous test coverage.

## init.sh output

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 2. Verificando archivos base del harness ────────────
[OK]    (all 10 files present)

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (22 features)

── 4. Lint (ruff) ──────────────────────────────────────
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
2 failed, 149 passed in 211.40s
[FAIL]  Hay tests rotos
```

The 2 failing tests (`tests/shared/test_models.py::test_create_person` and `test_create_credit`) are pre-existing failures caused by a `uq_people_slug` unique constraint violation in the shared test database. They fail identically on the original `main` code before any of my changes, as verified by `git stash && pytest tests/shared/test_models.py` (2 failed, 3 passed) then `git stash pop`.

All 29 admin tests (11 new auth tests + 18 pre-existing) pass green.
