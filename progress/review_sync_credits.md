# Review — feature sync_credits: Persistencia de people/credits en sync jobs

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] — bash init.sh termina sin errores (código de salida 0).
- C2: [x] — No hay print() de debug en el código nuevo.
- C3: [x] — No hay TODOs sin contexto en el código nuevo.
- C4: [x] — ruff check y ruff format --check pasan sin errores.
- C5: [x] — 190 tests pasan.
- C6: [N/A] — No hay modelos SQLAlchemy nuevos.
- C7: [N/A] — No hay migración Alembic.
- C8: [N/A] — No hay migración Alembic.
- C9: [N/A] — No hay nuevos route handlers; jobs.py usa async correctamente.
- C10: [N/A] — No hay nuevos endpoints.
- C11: [N/A] — No hay nuevos endpoints.
- C12: [N/A] — No hay nuevos endpoints.
- C13: [N/A] — No hay nuevos endpoints.
- C14: [N/A] — No se procesan fechas nuevas en jobs.py.
- C15: [N/A] — No hay datos de test con external_ids directos.
- C16: [N/A] — No hay on-demand fallback nuevo.
- C17: [N/A] — No hay on-demand fallback nuevo.
- C18: [x] — El test test_sync_movies_is_idempotent confirma idempotencia.
- C19: [x] — Un fallo en people no incrementa errors ni aborta el bucle (try/except anidado e independiente).
- C20: [x] — No hay lógica en routes.py.
- C21: [x] — jobs.py llama a funciones de servicio (service.py) y repositorio via sus módulos, no escribe queries SQLAlchemy propias.
- C22: [x] — No se devuelven modelos ORM directamente.

## Separación de capas

jobs.py llama a `_persist_movie_people`, `_persist_series_people`, `_persist_series_creators` y `_persist_book_authors` — todas funciones definidas en sus respectivos service.py — sin introducir queries SQLAlchemy propias en el scheduler. Correcto.

`get_work_detail` ya existía en OpenLibraryClient con timeout y manejo de 404. El implementer lo reutilizó en lugar de crear un método nuevo, lo que es la decisión correcta.

## Tests

- `test_sync_books_calls_get_work_detail_for_authors` — verifica llamada a get_work_detail y _persist_book_authors.
- `test_sync_movies_calls_persist_movie_people` — verifica llamada y tmdb_id correcto (args[2] == 88801).
- `test_sync_movies_persist_people_failure_does_not_increment_errors` — verifica degradación elegante: synced=1, errors=0 cuando _persist_movie_people lanza.
- `test_sync_series_calls_persist_series_people_and_creators` — verifica ambas funciones de series.
- `test_sync_movies_is_idempotent` — actualizado con mock de _persist_movie_people para evitar llamadas HTTP reales.

Todos los nuevos tests cubren el comportamiento especificado. El test de degradación elegante es especialmente importante y está correcto.

## Observaciones

Ningún cambio fuera de jobs.py y test_admin_sync.py. La lógica de aislamiento de errores (try/except anidado dentro del try/except principal) garantiza que un fallo de credits no escala al contador errors. Los logs siguen el patrón existente (logger.exception con context). Sin regresiones.

## Output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
190 passed in 251.37s (0:04:11)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo.
```
