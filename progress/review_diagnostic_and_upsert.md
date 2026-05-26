# Review — feature diagnostic_and_upsert: Logging de diagnóstico + Idempotencia de get-or-create

**Veredicto:** APPROVED

## Checkpoints aplicables

- C1: [x] — `bash init.sh` termina sin errores.
- C2: [x] — No hay `print()` de debug. Se usa `logging` exclusivamente.
- C3: [x] — No hay TODOs sin contexto.
- C4: [x] — `ruff check` y `ruff format --check` pasan sin errores.
- C5: [x] — 87 tests pasan.
- C6: [x] — No se tocan modelos; los existentes ya usan SQLAlchemy 2.0.
- C7: [x] — No se añaden migraciones.
- C8: [x] — No aplica (sin migración nueva).
- C9: [x] — No se tocan rutas.
- C10: [x] — No aplica.
- C11: [x] — No aplica.
- C12: [x] — No aplica.
- C13: [x] — No se añaden endpoints nuevos.
- C14: [x] — La conversión de fechas preexistente no se altera.
- C15: [x] — No se añaden tests con external_ids.
- C16: [x] — No aplica.
- C17: [x] — No aplica.
- C18: [x] — El upsert con ON CONFLICT DO UPDATE garantiza idempotencia en genre/platform.
- C19: [x] — Los errores de cada job siguen capturados; los cambios no alteran esa lógica.
- C20: [x] — No se tocan rutas.
- C21: [x] — Los upserts quedan en `repository.py`, no en `service.py`.
- C22: [x] — No aplica.

## Notas de revisión

### Conjunto 1 — Logging de diagnóstico

`backlogg/books/adapters/open_library.py`:
- `logger.warning` → `logger.error` en la rama de status != 200: correcto para producción en Render, donde los logs de WARNING pueden quedar filtrados por nivel por defecto.
- Se añade `logger.error` cuando `works` está vacío con la clave `list(data.keys())`: diagnóstico útil y sin side-effects.
- Se añade `logger.error` al final de `get_trending_books` con el total de works obtenidos: tiene sentido como diagnóstico temporal. El uso de `error` en un path de éxito es inusual semánticamente pero no viola ninguna convención del proyecto.

`backlogg/scheduler/jobs.py`:
- Dos `logger.error` añadidos en `sync_books`: antes del bucle (tamaño de la lista) y al salir del bucle (synced/errors/out_of). Mismo razonamiento: nivel agresivo pero justificado para visibilidad en producción durante diagnóstico activo.
- El import de `pg_insert` es movido al nivel de módulo en ambos repositorios (de dentro de la función `upsert_*` al top del fichero): correcto según convenciones Python.

### Conjunto 2 — Idempotencia de get-or-create

`backlogg/books/repository.py` — `_get_or_create_genre`:
- Patrón anterior: `SELECT ... WHERE slug = X` → INSERT si None. Vulnerable a race condition (dos workers en paralelo pueden INSERT el mismo nombre con slugs distintos).
- Patrón nuevo: `pg_insert(BookGenre).on_conflict_do_update(constraint="uq_book_genre_name", set_={"slug": slug}).returning(BookGenre.id)` seguido de `SELECT ... WHERE id = genre_id`.
- La constraint `uq_book_genre_name` sobre `name` está definida en el modelo (`backlogg/books/models.py` línea 56) y en la migración (`alembic/versions/0004_books.py` línea 30). El nombre de constraint coincide exactamente.
- La estrategia ON CONFLICT es sobre `name` (la constraint), pero el `set_` actualiza `slug`. Es coherente: si dos entradas tienen el mismo `name` con slugs distintos, el upsert converge al slug recibido. Correcto.

`backlogg/games/repository.py` — `_get_or_create_genre` y `_get_or_create_platform`:
- Mismo patrón aplicado simétricamente.
- `uq_game_genre_name` → modelo línea 80, migración `0005_games.py` línea 31.
- `uq_game_platform_name` → modelo línea 94, migración `0005_games.py` línea 113.
- Ambos nombres de constraint coinciden.

No se introducen imports circulares, no se rompe la separación de capas, no hay lógica de negocio fuera de `repository.py`.

## output de init.sh

── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
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
[OK]    feature_list.json válido (13 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
97 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
87 passed in 103.36s (0:01:43)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.

## Cambios requeridos

Ninguno.
