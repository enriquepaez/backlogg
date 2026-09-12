# Sesión actual

**Sin feature en curso.** El issue #34 quedó `resolved` en `issues_list.json`
(rama `fix/igdb_promotion_lane`, pendiente de merge). Resumen en
`progress/history.md`.

## Pendiente operativo

- **Rotar la credencial de Neon**: la `DATABASE_URL` de producción se pegó en el
  chat de la sesión del 2026-09-12 para hacer las mediciones de espacio. Sigue
  sin rotar.

## Siguiente: feature 75 `pgvector_item_embeddings`

Abre el bloque B de `progress/priority_order.md` y no empieza por código. La
medición del 2026-09-12 dejó **~69 MB libres** en Neon, y eso decide la
representación antes de escribir nada:

- `float32` a 384 dimensiones = ~180 MB solo de datos, más índice HNSW. **No
  cabe.**
- **Cuantización binaria** = 48 bytes/ítem ≈ **6 MB** para los 120.032, con
  `bit` de pgvector, distancia de Hamming y reranking encima. Es la única que
  entra sin cambiar de plan de Neon.

Decisión que hay que tomar con el usuario antes de lanzar implementer: aceptar
la pérdida de precisión de la cuantización binaria (mitigable con reranking del
top-N por coseno) o pagar Neon.
