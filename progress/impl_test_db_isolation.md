# Informe de implementación — Aislamiento de la DB de tests (issue 5)

Rama: `fix/test-db-isolation`
Fecha: 2026-07-05

## Archivos tocados

| Archivo | Cambio |
|---------|--------|
| `tests/conftest.py` | Reescrito: guardia de aislamiento, redirección global a `TEST_DATABASE_URL`, limpieza de la DB de test al inicio de sesión |
| `tests/test_conftest_guard.py` | **Nuevo** — 6 tests que validan la guardia de aislamiento |

No se tocó nada en `backlogg/`, `docs/` ni `.github/workflows/`.

## Qué se implementó y por qué

### 1. Guardia de seguridad (`_enforce_test_db_isolation`, a nivel de módulo en conftest)

Se ejecuta al importar `tests/conftest.py`, antes de recolectar ningún test.
Aborta toda la suite con `pytest.exit(..., returncode=1)` si:

1. `TEST_DATABASE_URL` está vacía (o solo espacios).
2. `TEST_DATABASE_URL` apunta a la **misma base** que `DATABASE_URL`. La
   comparación no es de string exacto sino de identidad `(host, nombre de DB)`
   vía `urlsplit`, para que diferencias cosméticas (query params como
   `?sslmode=require`) no burlen la guardia.
3. `backlogg.core.database` ya está en `sys.modules` — significaría que el
   engine de la app se construyó **antes** de la redirección y podría apuntar
   a la DB principal. Protege contra regresiones de orden de imports (p. ej.
   un plugin de pytest o un futuro conftest que importe la app antes).

Verificado en vivo: `TEST_DATABASE_URL="" uv run pytest` aborta inmediatamente
con `Exit: TEST_DATABASE_URL is empty — refusing to run...` sin ejecutar tests.

### 2. Redirección global a la DB de test (cierre de rutas de escape)

Auditoría de rutas por las que un test podía tocar `settings.DATABASE_URL`:

- **`tests/conftest.py`** (migraciones + engine): usaba `settings.DATABASE_URL`
  directamente. → Ahora usa `settings.TEST_DATABASE_URL`.
- **`backlogg.core.database`** (engine + `async_session_factory` + `get_db`):
  construye el engine a nivel de módulo desde `settings.DATABASE_URL`. Lo usan:
  - Los tests de endpoint que **no** hacen override de `get_db`
    (`test_admin_stats.py` fixture `client`, `test_admin_auth.py`,
    `test_cors_security.py`): con clave válida llegan a leer la DB vía el
    `get_db` real.
  - **`backlogg/scheduler/jobs.py`**: los 4 sync jobs abren sesión con
    `async_session_factory` directamente (líneas 62/114/169/232) y hacen
    `commit`. En `test_admin_sync.py` la mayoría de tests parchean la factory,
    pero los tests de error-path (`test_sync_*_catches_external_error`,
    `test_sync_movies_error_does_not_affect_sync_series`) **no** la parchean:
    el job abre sesión real antes de que el mock del cliente externo lance.

  **Cierre elegido**: en conftest, tras la guardia y antes de que se importe
  ningún otro módulo de la app, se hace
  `settings.DATABASE_URL = settings.TEST_DATABASE_URL` y
  `os.environ["DATABASE_URL"] = settings.TEST_DATABASE_URL`.
  Como `backlogg.core.database` crea su engine al importarse (y pytest importa
  conftest antes que cualquier módulo de test), **todos** los consumidores
  (`get_db`, `async_session_factory`, los sync jobs, Alembic vía env var, e
  incluso una instanciación fresca de `Settings()` — las env vars tienen
  prioridad sobre `.env` en pydantic-settings) quedan apuntando a la DB de
  test. La comprobación 3 de la guardia garantiza que esta suposición de orden
  no se rompa silenciosamente en el futuro. Esto evitó tocar `backlogg/core/database.py`.

- Ningún otro archivo crea engines ni lee `DATABASE_URL` (verificado con grep
  sobre `backlogg/` y `tests/`).

### 3. Migraciones Alembic

`alembic/env.py` ya prioriza la env var `DATABASE_URL` (y gestiona el strip de
`sslmode`). Como la env var queda fijada a la URL de test para todo el proceso,
el fixture `apply_migrations` se simplifica a `command.upgrade(...)`. No se
escribió ninguna migración nueva (leídas las 7 existentes en
`alembic/versions/` — no aplicaba).

### 4. Limpieza de la DB de test al inicio de cada sesión (ajuste justificado)

En `db_engine` (session scope), tras migrar, se hace
`TRUNCATE ... RESTART IDENTITY CASCADE` de todas las tablas públicas excepto
`alembic_version`. Justificación: varios caminos de código hacen `commit`
dentro del test (fallbacks on-demand en `movies/books/games/series/service.py`,
`search/repository.py`, sync jobs), y el rollback per-test del fixture `db` no
los deshace. Sin esta limpieza, residuos de una ejecución anterior de la
propia suite podrían romper ejecuciones futuras (mismo mecanismo por el que el
sync nocturno rompió los 2 tests en la DB compartida). Es seguro porque la
guardia garantiza que ese engine solo puede apuntar a la DB de test.

### 5. Tests (tests/test_conftest_guard.py)

6 tests unitarios de la guardia: parseo de identidad host+db, abort con URL
vacía, abort con URLs iguales, abort con misma DB pese a query params
distintos, paso con DBs distintas, y abort si `backlogg.core.database` ya
estaba importado.

### 6. Los 2 tests rotos

`tests/shared/test_models.py::test_credit_unique_constraint` y
`tests/movies/test_service.py::test_get_movie_fallback_passes_year_from_slug`
pasan **sin modificarlos**: la DB de test no contiene `tom-hardy` ni
`blade-runner-1982` (y la limpieza de sesión garantiza que siga así).

## Verificación

### bash init.sh — VERDE completo

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.x
[OK]    uv -> uv x.y
── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md ... CHECKPOINTS.md (todos OK)
── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (22 features)
── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
121 files already formatted
[OK]    ruff format pasa
── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
..                                                                       [100%]
218 passed in 347.58s (0:05:47)
[OK]    Todos los tests pasan
── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

218 tests = los 212 previos (incl. los 2 que fallaban) + 6 nuevos de la guardia.

### DB principal limpia tras correr la suite

Script asyncpg (scratchpad, sin imprimir credenciales) contra `DATABASE_URL`:
`SELECT count(*)` de slugs `LIKE '%-search-test%'` y `LIKE 'recommended-%'`
en `movies`, `series`, `books`, `games`:

```
connected to database: neondb
RESULT: CLEAN — no test fixtures in main DB
```

### Guardia en vivo

```
$ TEST_DATABASE_URL="" uv run pytest -q
E   _pytest.outcomes.Exit: TEST_DATABASE_URL is empty — refusing to run the
    test suite against DATABASE_URL. Point TEST_DATABASE_URL to a dedicated
    test database.
```
(0 tests ejecutados)

## Notas para el leader

- El workflow de CI (si corre pytest) necesitará `TEST_DATABASE_URL` definido
  — fuera de mi alcance por instrucción (`.github/workflows/`).
- La suite ahora tarda ~6 min contra Neon remoto; el TRUNCATE inicial añade
  <1s.
