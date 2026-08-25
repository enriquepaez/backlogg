# Orden de prioridad del backlog

> A diferencia de `progress/current.md`, este archivo **no se trunca** al
> cerrar sesión — sobrevive entre sesiones. Actualízalo (no lo vacíes) cuando
> cambien las prioridades o se complete/descarte algo de la lista.

Cuando este archivo tenga entradas pendientes, úsalo en vez del criterio por
defecto de `AGENTS.md` §4 ("menor id con dependencias satisfechas") para
elegir la siguiente tarea. Si un id de aquí ya no está en `pending`/`open`
en su lista de origen, sáltalo — no hace falta editar este archivo solo por
eso, basta con no repetirlo.

## Orden acordado con el usuario (2026-08-25)

Backlog acumulado en una sola sesión de repaso (audit 4 + reportes directos
del usuario sobre credits, tipos de item, categorías de juego, rating
externo, developer/publisher, plataformas, géneros y saltos de línea en
descripciones).

1. **Issue #16** (frontend) — `whitespace-pre-line` en overview. Trivial,
   sin dependencias, quick win.
2. **Backend 65** — `game_category_allowlist`. Antes de invertir en pulir la
   ficha de juego (plataformas, developer/publisher), decidir qué
   categorías IGDB quedan en el catálogo.
3. **Issue #15** (backend/ops) — backfill de credits vía
   `.github/workflows/backfill-sync.yml` (series primero, 100% roto; luego
   movies hasta agotar). No compite por el slot de "una feature a la vez"
   (no es código) — puede dispararse en paralelo con cualquier otro punto
   de esta lista, previa confirmación del usuario (acción sobre producción).
4. **Backend 66 → Backend 69 → Frontend FE-59** — `rating_display_internal_only` /
   `rating_internal_list_exposure` / `rating_badge_internal_only`. Backend 66
   done. Al empezar la implementación de FE-59 (2026-08-25) el implementer se
   bloqueó: los schemas de lista/grid (movies/series/books/games list items,
   trending, search, library, recommendations, similar items) nunca
   exponían `rating_internal`, solo los 4 schemas de detalle — feature 66 no
   lo cubrió. Se añadió **Backend 69** (`rating_internal_list_exposure`,
   depends_on: [66]) para cerrar ese hueco, incluyendo el gap de
   `catalog_search` (vista materializada de `/search`, sin columna
   `rating_internal` hoy). FE-59 queda bloqueada hasta que 69 esté `done`.
5. **Backend 67 → Frontend FE-61** — `game_developer_publisher_exposure` /
   `game_developer_publisher_display`. Ambas `done`, mergeadas (PR #170,
   #171).
5b. **Frontend FE-63** — `item_detail_fields_not_available_placeholder`.
   Surgida durante la QA de FE-61 (2026-08-25): el usuario pidió invertir el
   comportamiento "omitir si falta" de TODOS los campos opcionales de
   `buildFields` (los 4 tipos de producto, no solo developer/publisher) por
   un placeholder "no disponible" — ver detalle completo en
   `frontend_feature_list.json` id=62. Se ejecuta justo después del punto 5
   por ser una continuación directa de ese mismo trabajo, antes de seguir
   con el resto de la lista original.
6. **Frontend FE-57** — `catalog_card_type_visual_coding`. Independiente.
7. **Frontend FE-60** — `game_platform_brand_badges`. Independiente, la más
   grande de diseño (agrupar 60+ plataformas IGDB por familia de marca).
8. **Frontend FE-58** — `game_type_display_labels`. Pequeña, sin bloqueos.
9. **Frontend FE-62** — `genre_pills_prominence`. Pequeña, sin bloqueos.

Razonamiento: quick win primero: luego fundaciones de datos (categorías de
juego) antes de pulir UI que depende de esos datos; luego los pares
backend→frontend por dependencia real; luego el resto de frontend
independiente, ordenado de mayor a menor tamaño de trabajo.

## Añadido durante la sesión (2026-08-25)

10. **Backend 68** — `trending_books_games`. Surgido durante el trabajo de
    la feature 66: GET /trending hoy solo mezcla movies/series (vía TMDB
    trending, sin equivalente en Open Library/IGDB). Sin frontend pareja
    todavía — se añadirá cuando exista. No reordenado dentro de la lista
    original; se ejecuta después del punto 9 salvo que el usuario decida
    lo contrario.

## Cierre

Cuando el punto 9 (o el último que quede pendiente de esta lista) pase a
`done`/`resolved`: borra este archivo y quita el párrafo que lo referencia
en `AGENTS.md` §4. No dejar el puntero apuntando a una lista ya vacía.
