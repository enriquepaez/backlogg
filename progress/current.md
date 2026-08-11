# Sesión actual

Sin feature en curso. **FE-10 `item_detail` cerrada** (reviewer APPROVED, `done` en
`frontend_feature_list.json`) **+ 2 bugfixes cerrados** (fuera de backlog, encontrados en QA
manual del usuario, ambos APPROVED por el reviewer, resumen en `progress/history.md`):
1. `book_credits` — libros no mostraban autor pese a que el backend ya lo persistía como `Credit`
   role=AUTHOR; se expuso `credits[]` en `BookOut`.
2. `book_credits_empty_crash` — el fix anterior expuso un crash determinista cuando `credits` es
   `[]` (array vacío); fix defensivo aplicado en `getCredits`/`ItemCredits` (+ mismo patrón en
   `genres[]`/`platforms[]`).

Los tres bundled en la rama `feat/fe10-item-detail`, pendiente confirmación de ship (commit + push
+ PR).

## Siguiente feature disponible (M1)
**FE-11** `global_search` (id=12, depende de FE-6 `app_shell` ✅ y FE-2 `api_client` ✅ — ambas
satisfechas).
