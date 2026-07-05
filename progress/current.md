# Sesión actual

Fecha: 2026-07-05
Rama: feat/sync-slice-cursor

## Iniciativa "opción D" — completa

- Feature 23 `seed_config_wiring`: ✅ done, mergeada (PR #42).
- Feature 24 `sync_slice_cursor`: ✅ done. Pendiente: QA manual + ship.

Con esto el plan aprobado por el usuario para crecer el catálogo hasta ~10k
items populares por tipo queda implementado en código. Con los defaults
actuales (SEED_TOP_N=100, SYNC_SLICE_SIZE=200) el comportamiento nocturno no
cambia.

## Pendiente tras el merge (ops, no código)

En Render, para activar el crecimiento real:
- `SEED_TOP_N_MOVIES` / `SEED_TOP_N_SERIES` → subir hacia 10000 (tope real de
  TMDB popular/discover).
- `SEED_TOP_N_BOOKS` / `SEED_TOP_N_GAMES` → valorar objetivo (Open Library e
  IGDB no tienen el mismo tope de 10k; decidir según necesidad real).
- `SYNC_SLICE_SIZE` → 200 (o menos si se quiere ser más conservador con la
  duración del job). Ojo: IGDB hace 1 sola request y su adapter no batchea
  más allá de 500 — si se sube SYNC_SLICE_SIZE > 500, revisar
  `backlogg/games/adapters/igdb.py` primero (provocaría wrap prematuro en
  games). Anotado también en el review de la feature 24.
