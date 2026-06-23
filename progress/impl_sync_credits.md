# impl_sync_credits — Persistencia de people/credits en sync jobs

## Archivos modificados

- `backlogg/scheduler/jobs.py` — cambios principales
- `tests/test_admin_sync.py` — tests actualizados y nuevos

## Qué se implementó

### `backlogg/scheduler/jobs.py`

**Imports añadidos:**
```python
from backlogg.books.service import _persist_book_authors
from backlogg.movies.service import _persist_movie_people
from backlogg.series.service import _persist_series_creators, _persist_series_people
```

**`sync_movies`:** tras `session.flush()`, se llama a `_persist_movie_people(session, movie, tmdb_id)` dentro de un try/except propio. Si lanza excepción, solo se loguea — no incrementa `errors` ni aborta el bucle.

**`sync_series`:** tras `session.flush()`, se llama a `_persist_series_people(session, series, tmdb_id)` y, si `detail.get("created_by")` no está vacío, a `_persist_series_creators(session, series, created_by)`. La variable `detail` ya existía en el bucle (resultado de `get_series_detail`). Mismo criterio de error aislado.

**`sync_books`:** tras `session.flush()`, si `work_id` está disponible, se llama a `_ol_client.get_work_detail(work_id)` (método ya existente en `OpenLibraryClient`) y, si devuelve datos, a `_persist_book_authors(session, book, work_detail)`. Error aislado.

**`sync_games`:** no se toca — los `company_credits` se populan en `upsert_game`.

### Decisiones de diseño

- Se reutilizó `get_work_detail` (ya existente en `OpenLibraryClient`) en lugar de crear `get_work`. El método ya tiene timeout y manejo de 404.
- Los bloques try/except para people están **anidados dentro** del try/except principal de cada ítem, de forma que un fallo de credits no escala al contador `errors` (que solo cuenta fallos de upsert del ítem principal).
- No se modificó ningún módulo de servicio ni repositorio — solo `jobs.py` llama a las funciones de persistencia ya existentes.

### `tests/test_admin_sync.py`

- **Eliminado:** `test_sync_books_does_not_call_get_work_detail` — el comportamiento contrario ahora es el correcto.
- **Añadido:** `test_sync_books_calls_get_work_detail_for_authors` — verifica que `get_work_detail` y `_persist_book_authors` se llaman para libros con `work_id`.
- **Añadido:** `test_sync_movies_calls_persist_movie_people` — verifica que `_persist_movie_people` se llama una vez por película y con el `tmdb_id` correcto.
- **Añadido:** `test_sync_movies_persist_people_failure_does_not_increment_errors` — verifica degradación elegante: si `_persist_movie_people` lanza, `synced=1` y `errors=0`.
- **Añadido:** `test_sync_series_calls_persist_series_people_and_creators` — verifica que ambas funciones de series se llaman.
- **Actualizado:** `test_sync_movies_is_idempotent` — añadido mock de `_persist_movie_people` para evitar llamadas HTTP reales al TMDB en el test que usa la DB de test real.

## Output de `bash init.sh`

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
190 passed in 276.78s (0:04:36)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo.
```
