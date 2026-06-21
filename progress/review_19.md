# Review — feature 19: book_authors_people

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] — `bash init.sh` termina en verde, código de salida 0.
- C2: [x] — No hay `print()` de debug en ningún archivo modificado.
- C3: [x] — No hay TODOs sin contexto en el código nuevo.
- C4: [x] — `ruff check` y `ruff format --check` pasan sin errores.
- C5: [x] — 158 tests pasan.
- C6: [x] — No hay modelos nuevos; el código nuevo usa SQLAlchemy 2.0 (`select()`, `scalars()`, `AsyncSession`).
- C7: [x] — No hay migración nueva (las tablas `people`, `credits`, `external_ids` ya existen). Correcto.
- C8: [x] — No aplica (sin migración nueva).
- C9: [x] — No hay endpoints nuevos en esta feature; la ruta `GET /people/{slug}` existente ya era async.
- C10: [x] — No aplica (sin endpoints nuevos).
- C11: [x] — No aplica (sin endpoints nuevos).
- C12: [x] — No aplica (sin endpoints nuevos).
- C13: [x] — No aplica (sin endpoints nuevos). Los 7 tests del servicio y el test de repositorio cubren los acceptance criteria.
- C14: [x] — No hay fechas de APIs externas en el código nuevo (`last_synced_at` usa `datetime.now(UTC)` explícito).
- C15: [x] — IDs sintéticos únicos por test (`OLF19T{N}...`), nunca aparecen en datos reales de Open Library.
- C16: [x] — `_persist_book_authors` persiste en DB antes de cualquier devolución.
- C17: [x] — No aplica (sin nuevo endpoint con fallback).
- C18: [x] — `upsert_person` + `upsert_credit` son idempotentes via `ON CONFLICT DO UPDATE`. Test `test_persist_book_authors_idempotent` lo verifica explícitamente.
- C19: [x] — `try/except Exception` por autor dentro de `_persist_book_authors`. Tests `test_persist_book_authors_graceful_on_api_failure` y `test_persist_book_authors_skips_author_when_404` lo verifican.
- C20: [x] — Sin cambios en `routes.py`.
- C21: [x] — `service.py` no escribe queries SQLAlchemy directamente: toda la persistencia se delega a `people_repo.upsert_person`, `people_repo.upsert_credit` y `upsert_external_id`. La única llamada directa a `db` es `db.commit()` al final de `get_book`, que es el patrón establecido en esta capa.
- C22: [x] — `_persist_book_authors` no retorna datos. `get_book` retorna un `Book` ORM que el router serializa con Pydantic (patrón pre-existente sin cambio).

## Nota sobre `source='OPEN_LIBRARY'`

El acceptance criterion #3 de `feature_list.json` dice `source='openlibrary'` (minúscula), pero toda la codebase usa `"OPEN_LIBRARY"` (mayúscula) de forma consistente, incluyendo el upsert del work_id del libro (`service.py:127`), el sync (`jobs.py:179`) y el fallback de búsqueda (`search/service.py:104`). La implementación es internamente consistente con el resto del código. El spec tiene un typo; la implementación es correcta.

## Nota sobre `logger.error` para mensajes informativos

En `backlogg/books/adapters/open_library.py` (línea 80) y `backlogg/scheduler/jobs.py` (líneas 149, 192-196) hay llamadas a `logger.error` para mensajes informativos/de diagnóstico que no representan errores reales. Esto es pre-existente en `open_library.py` y fue añadido por el implementer en `jobs.py`. No es una violación de las reglas de las convenciones documentadas y ruff no lo marca, pero es una imprecisión semántica menor. No constituye motivo de rechazo.

## Nota sobre import local en `jobs.py`

`from backlogg.books.service import _persist_book_authors` está dentro del cuerpo de la función `sync_books` (línea 183) para evitar un import circular entre `scheduler/jobs.py` y `books/service.py`. Funciona correctamente, pasa ruff sin errores, y es el patrón más limpio dado el grafo de dependencias actual. No es una violación de arquitectura.

## Criterios de aceptación validados

1. [x] El sync de libros (`sync_books` + `get_book`) persiste autores en la tabla `people`.
2. [x] Cada autor tiene un credit con `role='AUTHOR'` (consistente con `ACTOR`, `DIRECTOR` en el resto del código) vinculado al libro.
3. [x] `external_ids` registra el ID de Open Library para cada autor con `source='OPEN_LIBRARY'`.
4. [x] `GET /people/{slug}` devuelve autores con sus créditos de libros — `_resolve_credits` extendida con rama `BOOK`.
5. [x] El sync es idempotente — `upsert_person` y `upsert_credit` usan `ON CONFLICT DO UPDATE`.
6. [x] Si la API de autores falla para un libro, el libro se persiste igualmente — `try/except Exception` por autor.
7. [x] Tests de repositorio y servicio pasan (7 tests nuevos en `test_service_authors.py`, 1 en `test_repository.py`).
8. [x] `bash init.sh` termina en verde.

## Output de init.sh

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
112 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
158 passed in 194.25s (0:03:14)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
