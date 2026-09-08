# Sesión actual

**Feature backend 90 `igdb_targets_seeding` — `done`, pendiente de ship.**
Rama `feat/igdb_targets_seeding`, 2026-09-09. Reviewer `APPROVED` (10/10
acceptance), QA manual del leader contra IGDB y la DB reales, `bash init.sh`
verde con **1634 tests**. Resumen completo en `progress/history.md`.

Falta **commit + push + PR con confirmación del usuario**. Nada más.

La feature 88 se mergeó el 2026-09-08 (PR #211).

## Si esta sesión se corta aquí

- El trabajo está **sin commitear** en la rama. Sin migración: `seed_targets`
  existe desde la `0035`.
- **La DB de dev quedó con el catálogo de games completo** de la QA: 32.740
  filas en `games` y 32.000 `seed_targets` de GAME, todos hidratados
  (`pending = 0`). Más los ~19.000 `seed_targets` de movies/series que dejó la
  QA de la 88. Es la DB local de Docker; no molesta, pero conviene saber de
  dónde salen.
- **Issue #34 registrado** en `issues_list.json`: el barrido de promoción de
  games no está automatizado. Es consecuencia de diseño de esta feature, está
  documentado, y cerrarlo cuesta 64 peticiones. No se implementó porque está
  fuera del acceptance.

## Siguiente

Con la 90 cerrada se agota el **bloque A** de `progress/priority_order.md` (la
fundación del catálogo). El siguiente punto es el **bloque B**, que empieza por
la **feature 75 `pgvector_item_embeddings`** — va después del bloque A a
propósito, para embeber el catálogo definitivo una sola vez en vez de
re-embeberlo tras cada cambio de siembra.

Antes de empezarla conviene actualizar el «Estado» de
`progress/priority_order.md`: las features 88 y 90 ya no están pendientes, y el
bloque A queda completo. Backend pendientes hoy: **75, 76, 77, 78, 79, 80, 82,
83**.
