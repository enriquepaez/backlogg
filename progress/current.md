# Sesión actual

**Sin feature en curso.** Las 88 y 90 están `done` y mergeadas (PR #211 y #212),
y el paso operativo que la 90 dejaba pendiente —completar el catálogo de games
en producción— se ejecutó el 2026-09-12. Resumen en `progress/history.md`.

Lo único abierto es esta rama `chore/games_catalog_completion_record`, que solo
lleva documentación: el runbook de `VACUUM FULL` en `docs/operations.md`, la
entrada de `progress/history.md` y el estado de `progress/priority_order.md`.

## Estado de producción (2026-09-12)

**120.032 ítems**: 57.237 movies · 32.688 games · 19.159 books · 10.948 series.
Base en **421 MB de ~490 utilizables**, o sea **~69 MB libres**.

El bloque A de `progress/priority_order.md` está completo: catálogo sembrado,
mantenido al día por el incremental diario, y sin topes artificiales.

## Siguiente: feature 75 `pgvector_item_embeddings`, y no empieza por código

Abre el bloque B. Antes de escribir nada hay una decisión de representación que
la medición de hoy ya acota:

- `float32` a 384 dimensiones = ~180 MB solo de datos, más índice HNSW. **No
  cabe** en 69 MB.
- **Cuantización binaria** = 48 bytes/ítem ≈ **6 MB** para los 120.032, con
  `bit` de pgvector, distancia de Hamming y un reranking encima. Es la única
  que entra sin cambiar de plan de Neon.

Lo que hay que decidir con el usuario antes de lanzar implementer: si se acepta
la pérdida de precisión de la cuantización binaria (mitigable con reranking del
top-N por coseno sobre un subconjunto), o si esto es el momento de pagar Neon.

## Pendiente menor

- **Rotar la credencial de Neon**: la `DATABASE_URL` de producción se pegó en el
  chat de la sesión del 2026-09-12 para hacer las mediciones.
- **Issue #34** (promoción de games sin automatizar) sigue abierto: tarea corta,
  64 peticiones, buen hueco antes de meterse en el bloque B.
