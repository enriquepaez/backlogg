# Sesión actual

Fecha: 2026-07-05
Rama: feat/books-popular-source

## Feature 25 `books_popular_source` — done (APPROVED), pendiente de ship

- Implementer + reviewer completados. Reviewer: APPROVED (todos los criterios,
  init.sh verde con 240 tests). Resumen movido a `progress/history.md`.
- `get_trending_books` → `get_popular_books` (search.json?q=*:*&sort=readinglog),
  sync_books actualizado, docs/external-apis.md con nota "Popular-books strategy".
- Pendiente: manual QA con el usuario → confirmación → commit + push + PR a main.

## Estado de la iniciativa "opción D" (crecer el catálogo)

- Feature 23 `seed_config_wiring`: ✅ done, mergeada (PR #42).
- Feature 24 `sync_slice_cursor`: ✅ done, mergeada (PR #43).
- **Incidente en producción (resuelto)**: con `SEED_TOP_N_*=10000` +
  `SYNC_SLICE_SIZE=200`, el nightly de verificación manual falló en movies y
  series (`curl exit 22` tras ~48-49 min, timeout de infraestructura ~15 min
  por request). Books y games sí completaron. Mitigado bajando
  `SYNC_SLICE_SIZE` a 100 en Render (ya aplicado por el usuario). Con slice=100
  el comportamiento es seguro pero muy lento: ~100 items/noche/tipo → ~3 meses
  para llegar a 10000 en movies/series/games.
- **Hallazgo adicional**: `books` no crece aunque el sync tenga éxito, porque
  usa `/trending/weekly.json` (Open Library), una lista acotada de un puñado
  de cientos de entradas — nunca se acercará a 10000 por muchas noches que
  pasen. No es un bug de la feature 24, es un límite real de esa fuente.

Conclusión del usuario: el goteo nocturno de 100/tipo es demasiado lento y
books está limitado a una fuente pequeña. Se decide pivotar hacia un backfill
directo (bypass del límite de Render) + arreglar la fuente de books. Nuevas
features creadas en `feature_list.json`:

## Feature 25 `books_popular_source` (pending, depends_on: [4])

Sustituir `/trending/weekly.json` por `search.json?q=*:*&sort=readinglog`.

**Investigación ya hecha (no repetir)** — probado en vivo contra la API real:
- `sort=edition_count` NO existe → error 500 silencioso (cualquier sort
  inválido da 500, no un mensaje claro).
- `sort=rating` sí existe pero ordena por `ratings_average` crudo →
  surfacea libros oscuros con pocas valoraciones (ratings_count bajo, 74-155).
  No sirve para "popular".
- `sort=readinglog` sí existe y es la métrica correcta: ordena por cuántos
  usuarios reales tienen el libro en su lista (want-to-read/reading/read).
  Con `q=*:*&sort=readinglog` los resultados son títulos genuinamente
  populares y reconocibles (Atomic Habits, Harry Potter, A Game of Thrones,
  Rich Dad Poor Dad...).
- `q=*:*` es válido (Solr match-all, cumple el mínimo de 3 caracteres) y
  devuelve `numFound: 43,343,337` works — pool enorme, sin problema de volumen.
- Paginación profunda confirmada: `offset` probado hasta 9900 con
  `sort=readinglog` → HTTP 200 en todos los casos. Escala muy por encima de
  lo que necesitamos.
- El adapter ya tiene un método (`search_book`, `open_library.py:98`) que usa
  `search.json` con el field set correcto:
  `key,title,author_name,first_publish_year,cover_i,subject,isbn` — reusar
  ese mismo field set para el nuevo método.
- Único caller en producción de `get_trending_books`: `scheduler/jobs.py:275`
  (sync_books). El resto de referencias son tests — renombrar/actualizar sin
  miedo a romper otros callers.

## Feature 26 `direct_backfill_sync` (pending, depends_on: [24, 25])

Script que reutiliza `sync_movies/series/books/games` (ya existentes) pero
ejecutado directo contra Neon (sin pasar por la request HTTP de Render que
tiene el techo de ~15 min). Diseño: llamar a las funciones de
`backlogg/scheduler/jobs.py` en bucle con un tramo grande (parámetro/env
propio del script, sin tocar `SYNC_SLICE_SIZE` de producción), hasta que el
offset devuelto haga wraparound a 0 (agotó el objetivo o la API) o se agote
un presupuesto de tiempo de seguridad (por debajo de las 6h de GitHub
Actions). Progreso persistido en `sync_cursors` (la misma tabla que usa el
nightly), así que backfill y nightly conviven sin conflicto.

**Gap encontrado que hay que arreglar dentro de esta feature**:
`backlogg/games/adapters/igdb.py` → `get_top_games` hace `per_request =
min(limit, 500)` pero **no pagina** más allá de un único request — un tramo
de backfill > 500 en games causaría wraparound prematuro. Los demás adapters
(TMDB movies/series, Open Library) sí paginan correctamente en bucle.

**Prerequisito operativo — el usuario debe hacerlo, no yo**: añadir 4 GitHub
Actions secrets nuevos (hoy solo existen `ADMIN_API_KEY` y `RENDER_API_URL`,
verificado con `gh secret list`):
- `DATABASE_URL` (Neon de producción)
- `TMDB_API_KEY`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

Añadir con `gh secret set <NOMBRE>` desde su propia terminal (no pegar los
valores en el chat).

## Siguiente sesión — por dónde seguir

1. Empezar por la feature 25 (no depende de secrets nuevos, se puede
   implementar ya): crear `feat/books-popular-source` desde `main`, plan en
   este archivo, implementer → reviewer → ship.
2. Feature 26 puede avanzar en paralelo en cuanto el usuario confirme que ha
   añadido los 4 secrets.
3. Recordar el estado real de producción ahora mismo: `SEED_TOP_N_*=10000` y
   `SYNC_SLICE_SIZE=100` en Render — seguro pero lento (~100/noche/tipo).
   Esto se queda así hasta que la feature 26 esté lista.
