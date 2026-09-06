# Sesión actual

- **Feature**: 74 — `credits_source_author_role`
- **Rama**: `feat/credits_source_author_role`
- **Inicio**: 2026-09-06
- **Estado**: in_progress
- **Punto de la cola**: `progress/priority_order.md` → Bloque A, punto 5
  (el 4, feature 87, se cerró el 2026-09-06)

## Objetivo

Poblar dos roles nuevos en `credits` para `MOVIE` y `SERIES` desde el `crew`
de los payloads de TMDB que ya se piden hoy, filtrando por **allowlist de
`job`**, nunca por `department == "Writing"`:

- `SOURCE_AUTHOR` — autor de la obra de origen. Es el puente cross-type
  libro → película (capa 0 de `docs/recommendations-plan.md`).
- `WRITER` — guionista. **Solo dato de ficha**, peso cero en el ranker.

La especificación completa ya está escrita y no hay que decidir nada:
`docs/schema.md` §`SOURCE_AUTHOR` vs `WRITER` (líneas ~422-440) y
`docs/recommendations-plan.md` §capa 0.

## Estado del código hoy (verificado)

- `credits.role` es un `String(50)` libre, sin enum: no hace falta migración
  para admitir roles nuevos.
- Los roles viven hoy como literales sueltos: `"ACTOR"`/`"DIRECTOR"` en
  `backlogg/movies/service.py:122,133`, `"ACTOR"`/`"CREATOR"` en
  `backlogg/series/service.py:113,138`, `"AUTHOR"` en `backlogg/books/`.
- **Movies**: `map_movie_credits()` ya recorre `crew`, pero solo se queda con
  `job == "Director"`. Es el único embudo — lo usan la ruta on-demand
  (`collect_movie_credits`), la siembra (`scheduler/jobs.py:443`) y el
  backfill (`jobs.py:1021`).
- **Series**: `map_series_cast()` **no mira `crew` en absoluto**; los
  `CREATOR` salen de `created_by` del detalle. Hay que añadir el tratamiento
  de `crew` en ese mismo embudo (`jobs.py:458`, `jobs.py:1036`, `service.py:176`).
- `backlogg/books/repository.py:223,240` ya tiene las consultas de autoría,
  pero solo de `BOOK` y solo `role == "AUTHOR"`.

## Plan

1. **Allowlists por dominio** — constantes nombradas (no strings sueltos
   repartidos), en un módulo compartido de credits, con los jobs exactos de
   `docs/schema.md`. `Story` y `Screenstory` **fuera** de `SOURCE_AUTHOR`.
   Los jobs de storyboard (`Story Artist`, `Head of Story`,
   `Story Supervisor`) no caen en ninguna lista y por tanto no se persisten.
2. **Movies** — extender el bucle de `crew` de `map_movie_credits` para
   emitir además `SOURCE_AUTHOR` y `WRITER` por allowlist.
3. **Series** — añadir el mismo bucle de `crew` al embudo de
   `map_series_cast` (renombrar a `map_series_credits` y actualizar los tres
   call sites, para que el nombre no mienta). Sin llamadas nuevas a TMDB: el
   payload de `/tv/{id}/credits` ya trae `crew`.
4. **Consulta cross-type** — dado un `person_id`, devolver sus obras en
   **todos** los `item_type`, tratando `{AUTHOR, SOURCE_AUTHOR}` como una
   sola clase de autoría, y **exigiendo** que la persona tenga además un
   credit `AUTHOR` sobre un libro del catálogo (filtro anti-traductor del
   job `Book`).
5. **Tests** — regresión de storyboard, exclusión de `Story`/`Screenstory`,
   adaptación real (guionista ≠ autor → `WRITER` y `SOURCE_AUTHOR` en
   personas distintas), y persona con obra en dos tipos enlazada en ambos
   sentidos.
6. **Bruno** — revisar si cambia algún contrato de `credits[]` en los detail
   endpoints; sincronizar `bruno/` si es el caso.

## Fuera de alcance

- Games: sin credits de persona, por decisión del 2026-09-04.
- Peso de estos roles en el ranker: es la feature 82.
- Migración de Alembic: no hace falta, `role` es texto libre.

## Riesgo abierto (a resolver antes de cerrar, no antes de implementar)

El criterio de aceptación «issue #15 verificado como resuelto para movies,
series **y** books» depende del borrado + siembra de producción, que sigue sin
ejecutarse. Se verifica contra la DB de dev en la QA manual; el cierre real del
#15 sigue atado a la siembra.
