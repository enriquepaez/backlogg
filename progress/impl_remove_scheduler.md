# Implementación: eliminar APScheduler in-process

Fecha: 2026-07-04
Rama: `refactor/remove-inprocess-scheduler`
Tarea: refactor puntual (fuera de `feature_list.json` — no se tocó ese archivo)

## Archivos tocados

| Archivo | Cambio |
|---|---|
| `backlogg/scheduler/setup.py` | **Eliminado** (era el único consumidor de APScheduler) |
| `backlogg/main.py` | Eliminados el lifespan completo, el import de `create_scheduler` y el import de `asynccontextmanager`. `FastAPI(title="Backlogg API")` sin `lifespan` |
| `pyproject.toml` | Eliminada la dependencia `apscheduler>=3.10.0` |
| `uv.lock` | Regenerado con `uv lock` (elimina `apscheduler`, `tzdata`, `tzlocal`) |

**Conservado intacto:** `backlogg/scheduler/jobs.py` (y `backlogg/scheduler/__init__.py`),
tal y como exige el alcance — lo importan `backlogg/admin/router.py` y
`tests/test_admin_sync.py`.

**No tocado:** `.github/workflows/`, `docs/`, `CLAUDE.md`, `feature_list.json`, `tests/`.

## Decisiones

1. **Lifespan eliminado por completo** en lugar de dejarlo vacío. El scheduler
   era su único contenido; `docs/conventions.md` no impone ningún patrón de
   lifespan (solo menciona `main.py` como punto de montaje de routers) y ningún
   test lo referencia. Un lifespan vacío sería código muerto.
2. **Sin cambios en tests.** Búsqueda exhaustiva de `create_scheduler`,
   `scheduler.setup` y `apscheduler` en `tests/`: cero referencias. El único
   test relacionado, `tests/test_admin_sync.py`, importa exclusivamente
   `backlogg.scheduler.jobs`, que se conserva.
3. **Eliminado `backlogg/scheduler/__pycache__/`** para evitar que el `.pyc`
   huérfano de `setup.py` enmascarase el borrado.

## Verificación

- `uv run python -c "from backlogg.main import app"` → **OK** (`import ok`).
- `uv run ruff check .` → **All checks passed!**
- `uv run pytest tests/test_admin_sync.py -q` → **16 passed** (los tests de los
  jobs de sync siguen verdes).
- `bash init.sh` → suite completa: **2 failed, 210 passed** → init.sh termina
  en FAIL. Ver siguiente sección.

### Los 2 fallos son PREEXISTENTES y ajenos a este refactor

Tests que fallan:
- `tests/movies/test_service.py::test_get_movie_fallback_passes_year_from_slug`
- `tests/shared/test_models.py::test_credit_unique_constraint`

**Evidencia de preexistencia:** con `git stash` (árbol idéntico a `main`,
commit `c8d3732`) los mismos 2 tests fallan con los mismos errores. Después se
restauraron los cambios con `git stash pop`.

**Causa raíz:** ambos tests asumen que ciertos datos no existen en la DB, pero
la suite corre contra la DB compartida de `settings.DATABASE_URL`, que el
nightly sync (arreglado en PR #39 y ejecutado con éxito) ha poblado con datos
reales:
- `test_credit_unique_constraint` inserta la persona `tom-hardy` →
  `UniqueViolationError: duplicate key ... "uq_people_slug"` (Tom Hardy ya
  existe por el sync de movies).
- `test_get_movie_fallback_passes_year_from_slug` espera que
  `blade-runner-1982` no esté en catálogo para forzar el fallback a TMDB →
  el registro ya existe, `search_movie` nunca se llama
  (`Expected 'search_movie' to be called once. Called 0 times.`).

El fixture `db` de `tests/conftest.py` limpia por `rollback()`, lo que no
protege frente a datos ya commiteados por procesos externos (el sync nocturno).

**Fuera de alcance de esta tarea** (regla: una sola tarea por sesión). Se
reporta al leader como incidencia separada: los tests dependientes del estado
de la DB compartida deberían aislarse (datos aleatorios por test, DB de test
dedicada, o limpieza previa).

## Output de `bash init.sh` (tramo final)

```
=========================== short test summary info ============================
FAILED tests/movies/test_service.py::test_get_movie_fallback_passes_year_from_slug
FAILED tests/shared/test_models.py::test_credit_unique_constraint - sqlalchem...
2 failed, 210 passed in 271.67s (0:04:31)
[FAIL]  Hay tests rotos

── 6. Resumen ──────────────────────────────────────────
[FAIL]  Entorno NO está listo. Resuelve los errores antes de avanzar.
```

Nota: los pasos previos de init.sh (deps, ruff, imports, migraciones) pasaron;
el único paso rojo es pytest por los 2 tests preexistentes descritos arriba.
Verificaciones dirigidas del refactor: todas verdes.
