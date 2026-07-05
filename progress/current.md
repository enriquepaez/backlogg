# Sesión actual

Fecha: 2026-07-04
Rama: refactor/remove-inprocess-scheduler

## Contexto

El sync nocturno fallaba todas las noches (10+ días). Causa: los 4 syncs del
workflow de GitHub Actions corrían como jobs paralelos contra la única
instancia free de Render. Arreglado en PR #39 (syncs secuenciales +
wake-up + timeouts). Run manual post-fix: success en 28m14s.

## Tarea en curso (fuera de feature_list.json — refactor puntual)

1. **[hecho — leader]** Endurecer paso `verify` del workflow: falla si algún
   `last_synced_at` tiene más de 2 horas (`.github/workflows/nightly-sync.yml`).
2. **[implementer]** Eliminar el APScheduler in-process: es código muerto en
   producción (la instancia free duerme a las 02:00 UTC y los CronTrigger
   nunca disparan; el sync real es el workflow de GitHub Actions).
   - Eliminar `backlogg/scheduler/setup.py` y el uso del scheduler en el
     lifespan de `backlogg/main.py`.
   - **Conservar** `backlogg/scheduler/jobs.py` (lo importa `admin/router.py`).
   - Quitar la dependencia `apscheduler` de `pyproject.toml` (+ `uv lock`).
   - Actualizar/eliminar tests que referencien el scheduler setup.
   - Resultado en `progress/impl_remove_scheduler.md`.
3. **[reviewer]** Veredicto como texto (tarea fuera del backlog — sin archivo).
4. **[leader]** Actualizar menciones a APScheduler en docs/CLAUDE.md.
5. **[hecho]** Ship: commit `9a32e26`, PR #40 abierto (pendiente de merge).
   Reviewer: APPROVED. Pasos 2-4 completados.

## Incidencia destapada (pendiente, tarea separada)

`init.sh` falla en main por 2 tests que asumen datos ausentes en la DB
compartida, ahora poblada por el sync nocturno funcional:
`test_credit_unique_constraint` (slug tom-hardy) y
`test_get_movie_fallback_passes_year_from_slug` (blade-runner-1982 ya en
catálogo). Relacionado con issue 5 de progress/issues.md (aislamiento de DB
de tests).

## Otras acciones de la sesión

- Routine cloud programada para verificar la run nocturna de mañana
  (2026-07-05 07:00 UTC): trig_01ETxfRXnMEZDbU76uDvoZF8.
