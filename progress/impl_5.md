# Implementation Report — Feature 5: Games

## Status
Implemented and verified. `bash init.sh` exits green (47 tests pass).

## Files Created

### Application code
- `backlogg/games/__init__.py` — empty module marker
- `backlogg/games/models.py` — SQLAlchemy models: `Game`, `GameGenre`, `GamePlatform`, `Company`, `CompanyCredit`, plus association tables `game_genres_join` and `game_platforms_join`
- `backlogg/games/adapters/__init__.py` — empty module marker
- `backlogg/games/adapters/igdb.py` — IGDB client with Twitch OAuth2, token caching + renewal, `get_game_by_slug`, `get_top_games`, and `game_to_dict`
- `backlogg/games/repository.py` — async DB operations: `get_game_by_slug`, `upsert_game` (with genres, platforms, companies)
- `backlogg/games/schemas.py` — Pydantic v2 schemas: `GameGenreOut`, `GamePlatformOut`, `GameOut`
- `backlogg/games/service.py` — on-demand fallback logic: DB lookup → IGDB → persist → 404
- `backlogg/games/routes.py` — FastAPI router with `GET /games/{slug}`

### Migration
- `alembic/versions/0005_games.py` — creates: `game_genres`, `games`, `game_genres_join`, `game_platforms`, `game_platforms_join`, `companies`, `company_credits`; adds `updated_at` triggers for `games` and `companies`; chains from revision `0004`

### Tests
- `tests/games/__init__.py` — empty
- `tests/games/test_repository.py` — repository tests against real DB (upsert, idempotency, not-found, multi-genres/platforms)
- `tests/games/test_service.py` — service tests with mocked IGDB client (found-in-db, fallback, 404)
- `tests/games/test_router.py` — endpoint tests via HTTPX async client (200, 404, fallback)
- `tests/games/test_igdb_client.py` — unit tests for token management and `game_to_dict` mapping

## Files Modified
- `backlogg/main.py` — added `games_router` import and `app.include_router(games_router)`

## Key Design Decisions

1. **Token caching with 60s buffer** — `IGDBClient` stores `_access_token` and `_token_expires_at` as instance variables. `_ensure_token()` is called before every IGDB request and renews only when less than 60 seconds remain, preventing race conditions on expiry edge.

2. **`game_type` integer → string mapping** — IGDB returns numeric game_type (0=MAIN_GAME, 1=DLC_ADDON, etc.). The adapter maps this to a descriptive string that matches the schema constraint `VARCHAR(30)`.

3. **Unix timestamp → `date`** — `first_release_date` from IGDB is a Unix timestamp in seconds. The adapter converts it explicitly with `datetime.fromtimestamp(ts, tz=UTC).date()` as required by conventions.

4. **Rating normalisation** — IGDB uses a 0–100 scale; divided by 10 and rounded to 1 decimal place to match the `NUMERIC(3,1)` schema column.

5. **Companies and company_credits** — The `upsert_game` repository function handles company persistence and `company_credits` upsert in a single transaction. The `on_conflict_do_nothing` on `uq_company_credit` ensures idempotency.

6. **Slug uniqueness in tests** — Each test uses a unique slug (with test-specific suffixes) to avoid `uq_external_id` violations when tests share the same rolled-back DB session.

7. **Platforms architecture** — `game_platforms` and `game_platforms_join` follow exactly the same pattern as genres. The `GamePlatformOut` is included in `GameOut.platforms[]` as required by `docs/api.md`.

## Reviewer Notes
- The `on_conflict_do_nothing` used for `company_credits` differs from the `on_conflict_do_update` used for `games` — this is intentional since credits are append-only relationships.
- `companies` table uses a GIN full-text index on `name`, matching `docs/schema.md`.
- The `updated_at` trigger for companies is included in the migration (there is no trigger for `company_credits` since it has no `updated_at` column).
- Test slugs in all three test files use unique suffixes (`-repo`, `-endpoint`, etc.) to prevent cross-test conflicts.

## bash init.sh output
```
47 passed in 61.17s (0:01:01)
[OK]    Todos los tests pasan
[OK]    Entorno listo. Puedes empezar a trabajar.
```
