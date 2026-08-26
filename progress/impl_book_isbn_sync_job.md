# Implementación — bugfix: sync_books nunca persiste isbn

**Rama:** `fix/book_isbn_sync_job`
**Tipo:** bugfix puntual, fuera de `backend_feature_list.json` (no se tocó
ningún estado de feature).

## Causa

`sync_books` (`backlogg/scheduler/jobs.py`) reconstruye a mano un
`search_doc` reducido para pasárselo a `book_to_dict`
(`backlogg/books/adapters/open_library.py`). Esa reconstrucción copiaba
`title`, `key`, `first_publish_year`, `cover_i`/`cover_id`, `subject` y
`author_name` desde `raw`, pero **no** `isbn` — aunque `raw` sí trae ese
campo (`get_popular_books`/`_fetch_popular_page` ya lo piden a Open
Library con `fields=...,isbn`). `book_to_dict` hace
`search_doc.get("isbn", [])`, así que para cualquier libro creado vía el
job nocturno el resultado era siempre `[]` → `isbn=None` en el `Book`
persistido, aunque Open Library sí tuviera el dato.

El único camino que sí funcionaba era el fallback on-demand
(`books/service.py::get_book`), que pasa el `search_doc` completo de Open
Library (incluyendo `isbn`) directamente a `book_to_dict` sin
reconstrucción manual — por eso la QA de la feature 71 (`book_isbn_field`,
con "the-hobbit" y "dune" creados vía fallback) no detectó el bug.

## Archivos modificados

- `backlogg/scheduler/jobs.py` — una línea: se añade `"isbn": raw.get("isbn",
  [])` al `search_doc` que `sync_books` construye antes de llamar a
  `book_to_dict`. No se tocó ningún otro campo del `search_doc`
  (`title`/`key`/`first_publish_year`/`cover_i`/`subject`/`author_name`
  siguen igual, ya se copiaban correctamente) ni `book_to_dict` ni
  `original_language` ni nada de la feature 70/71.

- `tests/test_sync_genre_slug_collision.py` — se añadió
  `test_sync_books_persists_isbn_from_raw_doc`, siguiendo el patrón ya
  existente en el mismo archivo (`test_sync_books_colliding_genre_slugs_across_docs`):
  mockea únicamente `_ol_client.get_popular_books` (devolviendo un doc con
  `isbn: ["9780000000001", "9780000000002"]`) y `get_work_detail`, usa el
  `db` real de test (fixture `db`, no un mock de sesión) como
  `async_session_factory`, ejecuta `sync_jobs.sync_books()` de punta a
  punta (incluye el `upsert_book` real) y verifica el `Book` **persistido
  en DB** (`select(Book).where(Book.slug == ...)`), aserta
  `book.isbn == "9780000000001"` (primer ISBN de la lista, según la
  decisión ya tomada en la feature 71 de `book_to_dict`). No mockea
  `book_to_dict` — cubre el flujo real de construcción del `search_doc`
  dentro de `sync_books`, que es exactamente donde estaba el bug.

  Verificado que el test es una regresión real: revirtiendo temporalmente
  el fix en `jobs.py` (`git stash`) el test falla con
  `AssertionError: assert None == '9780000000001'`; con el fix aplicado
  pasa.

- `progress/current.md` — plan de la sesión (ya existía, sin cambios de
  mi parte más allá de lo escrito por el leader).

## Fuera de scope (no tocado)

- `book_to_dict` y el resto de campos de `search_doc`.
- `original_language`.
- Cualquier feature del `backend_feature_list.json` (no se cambió ningún
  `status`).

## Output completo de `bash init.sh`

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (70 features)

── 4. Lint (ruff) ──────────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
All checks passed!
[OK]    ruff check pasa
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
286 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
........................................................................ [  6%]
........................................................................ [ 13%]
........................................................................ [ 20%]
........................................................................ [ 27%]
........................................................................ [ 33%]
........................................................................ [ 40%]
........................................................................ [ 47%]
........................................................................ [ 54%]
........................................................................ [ 61%]
........................................................................ [ 67%]
........................................................................ [ 74%]
........................................................................ [ 81%]
........................................................................ [ 88%]
........................................................................ [ 95%]
.....................................................                    [100%]
1061 passed in 37.21s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
