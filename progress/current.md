# Sesión actual

Fecha: 2026-07-05
Rama: fix/test-db-isolation

## Tarea: Issue 5 — aislar tests de la DB de producción + limpieza

Contexto: el sync nocturno (funcional desde PR #39) puebla la DB compartida
que usaba la suite de tests → 2 tests rotos en main (`init.sh` en rojo).
Además había fixtures de test commiteadas en la DB de producción.

### Hecho (leader)

- DB `backlogg_test` creada en el mismo servidor Neon.
- `TEST_DATABASE_URL` añadida a `.env` local (misma conexión, database
  backlogg_test) y a `ci.yml` (+ paso `CREATE DATABASE backlogg_test` en el
  servicio Postgres del runner).
- Borradas 6 filas falsas de producción (verificadas una a una antes):
  movies `inception-2010-search-test` y `recommended-movie-2008`, series
  `breaking-bad-2008-search-test` y `recommended-series-2015`, book
  `dune-1965-search-test`, game `witcher-3-2015-search-test` (+1
  external_id huérfano). `catalog_search` refrescada.
- Limpieza de progress/: eliminados impl_*/review_* obsoletos, history.md
  actualizado con PRs #39 y #40, estados de issues.md al día.

### Hecho (implementer — 2026-07-05)

- `tests/conftest.py` reescrito: guardia de aislamiento (aborta si
  `TEST_DATABASE_URL` vacía, si apunta a la misma DB que `DATABASE_URL`
  —comparación por host+dbname, inmune a query params— o si
  `backlogg.core.database` se importó antes del override), redirección
  global `settings.DATABASE_URL = TEST_DATABASE_URL` + env var (cierra
  `get_db`, `async_session_factory` de los sync jobs y Alembic), y
  TRUNCATE de la DB de test al inicio de sesión (los commits mid-test de
  los fallbacks/jobs no los deshace el rollback per-test).
- Nuevo `tests/test_conftest_guard.py` (6 tests de la guardia).
- Los 2 tests rotos pasan sin modificarlos. `init.sh` verde: 218 tests.
- DB principal verificada limpia tras la suite (sin slugs `%-search-test%`
  ni `recommended-%`).
- Detalle completo en `progress/impl_test_db_isolation.md`.

### Pendiente

- Reviewer: ✅ APPROVED (sin rutas de escape; TRUNCATE seguro; CI correcto).
- Ship con confirmación del usuario.
- Verificación pasiva: routine cloud comprueba la run nocturna programada
  a las 07:00 UTC (trig_01ETxfRXnMEZDbU76uDvoZF8).
