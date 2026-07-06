# Sesión actual

Fecha: 2026-07-05
Rama: feat/direct-backfill-sync

## Bugfix `fix/sync-genre-slug-collision` — APPROVED, pendiente de ship

Descubierto al ejecutar el primer backfill real de books (run 28787545315):
"success" con 0 libros persistidos. Colisión de slug de género → sesión
envenenada → tramo en rollback y cursor clavado. Fix + 7 tests, APPROVED.
Tras merge: relanzar backfill de books (cursor BOOK quedó en 0) y verificar
crecimiento real en Neon (books estaba en 157).

## Feature 26 `direct_backfill_sync` — done, shippeada (PR #45 + fix import PR #46)

Feature 25 `books_popular_source`: ✅ done, mergeada (PR #44).

- Implementer + reviewer completados. Reviewer: APPROVED (init.sh verde,
  254 tests). Resumen movido a `progress/history.md`.
- Entregado: `scripts/backfill_sync.py`, workflow `backfill-sync.yml`
  (workflow_dispatch: content_type + seed_top_n), param `slice_size` en los
  4 jobs, paginación IGDB >500 con throttle, docs/verification.md, 14 tests.
- Pendiente: manual QA con el usuario → confirmación → commit + push + PR.

**Nota operativa (sigue pendiente)**: los 4 secrets del workflow
(`DATABASE_URL`, `TMDB_API_KEY`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`)
NO aparecen en `gh secret list` (solo `ADMIN_API_KEY` y `RENDER_API_URL`),
aunque el usuario dijo haberlos añadido. Sin ellos el workflow fallará.
Verificar antes del primer dispatch.

**Estado de producción**: `SEED_TOP_N_*=10000`, `SYNC_SLICE_SIZE=100` en
Render. Tras mergear esta feature: lanzar el backfill por tipo desde Actions
(input seed_top_n=10000) y repetir hasta stop_reason=wraparound.
