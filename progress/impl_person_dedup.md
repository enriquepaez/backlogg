# impl_person_dedup

## Files created or modified

### Modified
- `backlogg/shared/external_ids.py` — added SELECT-before-INSERT guard in `upsert_external_id`
- `tests/test_person_dedup.py` — added 2 new tests for `upsert_external_id` idempotency and conflict guard
- `backlogg/people/repository.py` — (previous session) added `get_person_id_by_external` and `get_person_by_id`
- `backlogg/movies/service.py` — (previous session) added `_get_or_create_person_tmdb` helper
- `backlogg/series/service.py` — (previous session) added `_get_or_create_person_tmdb` helper
- `backlogg/books/service.py` — (previous session) added `_get_or_create_person_ol` helper

## What was implemented and why

### Remaining root cause after previous fix

The previous session added `_get_or_create_person_tmdb` in the service layer, which does a lookup-by-external-id before creating a new person. This correctly handles the case where the same TMDB person appears across two *different* requests (e.g. two movies synced separately).

However, it does NOT handle the case where the same TMDB person appears **multiple times within the same movie's credits response** (e.g., appearing in both `cast[]` and `crew[]`, or appearing twice in the cast list). In that scenario:

1. First occurrence: `get_person_id_by_external` returns `None` (not yet in DB).
2. Person is created and `upsert_external_id` is called — the row is flushed but not committed.
3. Second occurrence: `get_person_id_by_external` runs a SELECT — but SQLAlchemy async sessions using PostgreSQL's `REPEATABLE READ` or the autobegin transaction may not reflect the flushed-but-not-committed row in all driver configurations, returning `None` again.
4. A second `upsert_person` + `upsert_external_id` is called, which tries to INSERT the same `(source, external_id)` pair, hitting `uq_external_id` and raising `IntegrityError`.

### Fix: SELECT-before-INSERT in `upsert_external_id`

Added a guard at the top of `upsert_external_id` that queries for any existing row matching `(source, external_id)` before attempting the INSERT. If found, it returns the existing row immediately (first-claim-wins). This is the correct layer to place the guard because:
- It is always called for every external ID link, regardless of which service calls it.
- The guard SELECT reads from the same session/transaction and will see rows flushed earlier in the same transaction.
- It avoids any reliance on the service-layer cache staying coherent across async awaits.

### New tests (2)

Both tests are in `tests/test_person_dedup.py`:

1. `test_upsert_external_id_same_source_external_id_different_item_no_error` — creates two Person rows, calls `upsert_external_id` with the same `(source, external_id)` but different `item_id`. Verifies no exception is raised and the returned row still belongs to the first person (first-claim-wins).

2. `test_upsert_external_id_same_source_external_id_same_item_is_idempotent` — calls `upsert_external_id` twice with identical `(source, external_id, item_id)`. Verifies the same row is returned both times with no error.

## Output of `bash init.sh`

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (22 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
121 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
200 passed in 303.32s (0:05:03)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Live endpoint verification

`GET /movies/the-truman-show-1998` returned HTTP 200 with title "The Truman Show" and 11 credits.
No IntegrityError. Previously this endpoint returned 500.
