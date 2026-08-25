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
4. **Backend 66 → Frontend FE-59** — `rating_display_internal_only` /
   `rating_badge_internal_only`. Pareja con dependencia real; backend
   primero.
5. **Backend 67 → Frontend FE-61** — `game_developer_publisher_exposure` /
   `game_developer_publisher_display`. Misma lógica.
6. **Frontend FE-57** — `catalog_card_type_visual_coding`. Independiente.
7. **Frontend FE-60** — `game_platform_brand_badges`. Independiente, la más
   grande de diseño (agrupar 60+ plataformas IGDB por familia de marca).
8. **Frontend FE-58** — `game_type_display_labels`. Pequeña, sin bloqueos.
9. **Frontend FE-62** — `genre_pills_prominence`. Pequeña, sin bloqueos.

Razonamiento: quick win primero: luego fundaciones de datos (categorías de
juego) antes de pulir UI que depende de esos datos; luego los pares
backend→frontend por dependencia real; luego el resto de frontend
independiente, ordenado de mayor a menor tamaño de trabajo.

## Cierre

Cuando el punto 9 (o el último que quede pendiente de esta lista) pase a
`done`/`resolved`: borra este archivo y quita el párrafo que lo referencia
en `AGENTS.md` §4. No dejar el puntero apuntando a una lista ya vacía.
