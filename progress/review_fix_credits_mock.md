# Review — feature fix_credits_mock: Fix HTTP call leak in service tests

**Veredicto:** APPROVED

## Checkpoints

Checkpoints aplicables a este cambio (solo tests, sin nuevos endpoints ni modelos):

- C1: [x] — `bash init.sh` termina con código 0.
- C2: [x] — Sin `print()` de debug en el código nuevo.
- C3: [x] — Sin TODOs en el código nuevo.
- C4: [x] — `ruff check` y `ruff format --check` pasan sin errores.
- C5: [x] — 78 tests pasan, 0 fallos.
- C6: [N/A] — No hay modelos nuevos.
- C7: [N/A] — No hay migración nueva.
- C8: [N/A] — No hay migración nueva.
- C9: [N/A] — No hay endpoints nuevos.
- C10: [N/A] — No hay endpoints nuevos.
- C11: [N/A] — No hay endpoints nuevos.
- C12: [N/A] — No hay endpoints nuevos.
- C13: [N/A] — No hay endpoints nuevos.
- C14: [N/A] — No hay conversiones de fechas nuevas.
- C15: [N/A] — No hay nuevos datos de test con external_ids.
- C16: [N/A] — No aplica.
- C17: [N/A] — No aplica.
- C18: [N/A] — No aplica.
- C19: [N/A] — No aplica.
- C20: [N/A] — No hay cambios en routes.py.
- C21: [N/A] — No hay cambios en service.py.
- C22: [N/A] — No hay cambios en service.py.

## Análisis del cambio

### tests/movies/test_service.py — líneas 81-86
`patch.object(service._tmdb, "get_movie_credits", ...)` es correcto.
El método mockeado existe en `backlogg/movies/adapters/tmdb.py:50` y es llamado
desde `backlogg/movies/service.py:31` vía `_tmdb.get_movie_credits(tmdb_id)`.
El valor de retorno `{"cast": [], "crew": []}` es structuralmente válido: el
código en `_persist_movie_people` consume exactamente `.get("cast", [])` y
`.get("crew", [])`.

### tests/series/test_service.py — líneas 81-86
`patch.object(service._tmdb, "get_series_credits", ...)` es correcto.
El método mockeado existe en `backlogg/series/adapters/tmdb.py:50` y es llamado
desde `backlogg/series/service.py:31` vía `_tmdb.get_series_credits(tmdb_id)`.
El valor de retorno es igualmente válido para `_persist_series_people`.

### Convenciones
- Los tests de servicio mockean el adaptador externo, tal como exige `docs/conventions.md`.
- No se introducen llamadas HTTP reales ni dependencias nuevas.
- El fix es mínimo y no afecta ningún otro test.

## Output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.4
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

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
[OK]    feature_list.json válido (10 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
92 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
78 passed in 85.84s (0:01:25)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
