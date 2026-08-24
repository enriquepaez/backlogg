# Sesión actual — fix/issue-14-search-fanout-completeness

## Tarea
Bugfix de `issues_list.json` #14 (no es una feature de `backend_feature_list.json`).
"El fan-out de búsqueda a APIs externas solo dispara con 0 resultados locales y
solo ingesta top-1/top-5, dejando el catálogo incompleto para franquicias con
contenido parcialmente sincronizado."

## Plan (recibido del leader, implementado tal cual)

1. `backlogg/search/service.py`: trigger de fan-out pasa de `total > 0` a
   `len(results) >= limit` (página incompleta, no solo cero resultados).
2. Ingestión múltiple mapeada desde page/offset (sin estado persistido nuevo):
   - `_FANOUT_LIMIT` (5) → `_FANOUT_PAGE_SIZE` (20), constante única.
   - `_ingest_movies/_ingest_series/_ingest_books/_ingest_games` pasan a firma
     `(q, page, limit)`, derivan `external_page` determinísticamente y hacen
     upsert de TODOS los hits de esa página externa (con `db.begin_nested()`
     por item, como ya hacía `_ingest_games`).
   - `TMDBClient.search_movie` / `TMDBSeriesClient.search_series`: añadir
     `page`, devolver lista completa de resultados (no `results[0]`).
   - `OpenLibraryClient.search_book`: añadir `page`, aplicar `_ol_search_retry`,
     devolver lista de `docs`.
   - `IGDBClient.search_games`: añadir `offset`, añadir retry con `tenacity`
     (patrón `_tmdb_retry`).
3. `backlogg/search/repository.py`: añadir `, id` como clave secundaria de
   `ORDER BY` en ambas ramas (con/sin `q`) — estabilidad de paginación.
4. Docs: `backlogg/search/routes.py` (description + docstring) y
   `docs/api.md` (fallback section + rate-limit paragraph) — reflejar el
   nuevo trigger y que se ingesta más de un hit.
5. Rate limit (`RATE_LIMIT_SEARCH_FALLBACK`) sin cambios.

## Archivos NO tocar
`apps/web/**`, `RATE_LIMIT_SEARCH_FALLBACK`, sin tabla/cursor nuevo.

## Estado
Implementación completa, `bash init.sh` en verde (979 tests). Ver informe
completo en `progress/impl_issue-14.md`. Pendiente de review — no se marcó
el issue como `resolved` en `issues_list.json`.

## Follow-up en la misma rama: perf fix (QA manual)

QA manual reportó búsqueda muy lenta tras el fix de #14 ("como cargar todas
las páginas"). Causa raíz: `_ingest_movies`/`_ingest_series`/`_ingest_books`
hacían hasta `_FANOUT_PAGE_SIZE` (20) llamadas de detalle HTTP secuenciales
por fuente dentro de la misma request, aunque el caller solo pida `limit`
resultados por página.

Fix en `backlogg/search/service.py` (sin tocar `_external_page()` ni
adapters):
1. El trabajo caro (detail-fetch por ítem en movies/series/books, upsert por
   ítem en games) se acota a `results[:limit]`, no a los 20 hits completos de
   la página externa mapeada. La búsqueda externa se sigue pidiendo con
   `_FANOUT_PAGE_SIZE=20` para no desalinear `_external_page()`.
2. Las llamadas de detalle de movies/series/books se paralelizan con
   `asyncio.gather(..., return_exceptions=True)` acotadas por
   `asyncio.Semaphore(_DETAIL_FETCH_CONCURRENCY=5)`. Fase de red (paralela) y
   fase de persistencia a DB (secuencial, por `begin_nested()` por ítem) van
   separadas — la `AsyncSession` no soporta escritura concurrente.
3. `_ingest_games` solo recibió el cambio de cap (#1); IGDB ya devuelve todo
   en bulk, sin detail-call por ítem.
4. Docstrings actualizados en `backlogg/search/service.py`,
   `backlogg/search/routes.py` y `docs/api.md` ("todos los hits" →
   "hasta `limit` hits").

Tests nuevos en `tests/test_search_fanout_ingestion.py` (7 nuevos, 11 total
en el archivo): cap a `limit` para movies/series/books/games, concurrencia
de detail-fetch para movies/series (contador de solapamiento), y aislamiento
de fallos (un detail-fetch que falla no aborta los demás ítems).

`bash init.sh` verde: 986 tests, ruff check y format OK. No se hizo commit
(pendiente de confirmación del usuario).

## Segundo follow-up en la misma rama: orden de desempate por rating (QA manual)

QA manual (queries reales vía psql contra `backlogg-db` local) confirmó que
el desempate `rating_external DESC NULLS LAST` de la ronda anterior casi
nunca se aplicaba: `ts_rank` rara vez es EXACTAMENTE igual entre dos filas
con títulos distintos, así que con `ORDER BY desc(rank_expr), rating_external
DESC NULLS LAST, id` el rating nunca llegaba a decidir. Ejemplo real
("batman"): "Batman: Arkham City - Arkham City Skins Pack" (sin rating,
rank=0.09421459) quedaba por delante de "Batman: Arkham Asylum - Game of the
Year Edition" (rating 8.6, rank=0.091906235).

Fix en `backlogg/search/repository.py` (`SearchRepository.search()`, rama
`if q is not None:`): se invierte el orden de las dos primeras claves de
`ORDER BY` — `rating_external DESC NULLS LAST` pasa a ser la clave
PRINCIPAL, `desc(rank_expr)` (ts_rank) pasa a ser el desempate entre ítems
con la misma valoración (incluyendo NULL vs NULL, agrupados al final y
ordenados entre sí por relevancia de texto), `id` sigue como último
desempate para estabilidad de paginación (issue #14). Solo cambia el
`ORDER BY`; el `WHERE search_vector @@ plainto_tsquery(...)` (filtro de
relevancia) no se toca. Docstring del método actualizado para reflejar el
nuevo orden. Rama `else` (sin `q`) y `service.py`/adapters sin cambios.

Tests en `tests/test_search.py`:
- `test_search_tied_rank_orders_by_rating_external_desc` (existente, misma
  fixture `tied_rank_seeded_db`) sigue pasando sin cambios — dos filas con
  título IDÉNTICO (mismo ts_rank), distinto rating: sigue ganando la de
  mayor rating, ahora como criterio principal en vez de desempate.
- Nuevo: `test_search_distinct_rank_orders_by_rating_external_over_ts_rank`
  con fixture `distinct_rank_seeded_db` — dos filas con ts_rank DISTINTO
  (verificado con queries psql directas contra la producción real de
  `search_vector`, migración 0028: "Batman" vs "Batman Batman Batman Arkham
  City Skins Pack", esta última con ts_rank estrictamente mayor por
  repetición de la palabra de búsqueda) pero rating opuesto a lo que ts_rank
  sugeriría (la de rank más bajo tiene rating 9.0, la de rank más alto no
  tiene rating). Confirma que ahora gana la de mayor rating, no la de mayor
  ts_rank — el caso real reportado en QA que el fix anterior no cubría.

`bash init.sh` verde: 988 tests, ruff check y format OK. No se hizo commit
(pendiente de confirmación del usuario).

## Tercer follow-up en la misma rama: página 1 siempre comprueba fan-out (QA manual, con psql)

QA manual (confirmado en vivo con psql contra `backlogg-db` local) encontró
que `SearchService.search()` solo dispara fan-out cuando la página local
sale incompleta (`len(results) < limit`). Para queries amplias y populares
("final fantasy", 111 filas locales) siempre hay de sobra para llenar
cualquier página, así que el fan-out nunca se dispara y un ítem tan conocido
como "Final Fantasy XIV" quedaba fuera hasta que el usuario adivinó el
término exacto "final fantasy xiv" (que sí venía corto en local). El
ranking (arreglado en la ronda anterior) no era el problema — el trigger
nunca llegaba a dispararse para queries amplias-pero-completas.

Fix en `backlogg/search/service.py` (`SearchService.search()`), reutilizando
la caché ya existente `backlogg/core/cache.py` (`get_cache()`), mismo patrón
que `core/rate_limit.get_rate_limiter`/`core/email.get_email_sender`:

1. Constante nueva `_FANOUT_QUERY_CACHE_TTL_SECONDS = 600` (10 min) y helper
   `_fanout_cache_key(q, item_type)` → `f"search_fanout:{item_type or 'all'}:{q.strip().lower()}"`
   (normalizado a minúsculas/strip, scoped por tipo).
2. El trigger pasa a: `page_incomplete or (page == 1 and not already_checked_recently)`,
   siempre con `q is not None` como condición previa. `page_incomplete`
   (comportamiento existente, cualquier página) no se toca — sigue
   disparando siempre que la página sale corta, sin que la caché intervenga
   nunca para SUPRIMIRLO (regresión probada explícitamente). El chequeo de
   caché (`cache.get(fanout_cache_key)`) solo decide si se dispara en
   páginas 1 YA completas.
3. Justo después de `enforce_search_fallback` y antes de lanzar las tareas
   de fan-out, si `page == 1`, se marca `cache.set(fanout_cache_key, True,
   _FANOUT_QUERY_CACHE_TTL_SECONDS)` — así una request idéntica (mismo
   `q`/`item_type`, página 1) dentro de los 10 minutos no vuelve a disparar
   fan-out. `limit` no forma parte de la clave (caso de borde aceptado, el
   frontend siempre usa el mismo `SEARCH_PAGE_SIZE`).
4. Docstrings actualizados en `backlogg/search/service.py` y
   `backlogg/search/routes.py` (description + docstring del handler).
   `docs/api.md` (sección "External fallback" en inglés y en español, y el
   párrafo de rate-limit) ajustado para reflejar que la página 1 comprueba
   las APIs externas al menos una vez por TTL aunque ya esté llena.

Tests nuevos/ajustados en `tests/test_search.py`:
- `test_search_fallback_page1_fires_first_time_even_when_local_page_full`
  (reemplaza a `test_search_fallback_not_fired_when_local_results_exist`,
  cuya premisa quedó obsoleta): página 1 ya llena (`limit=1`, 1 resultado
  local) SÍ dispara fan-out la primera vez.
- `test_search_fallback_page1_not_refired_within_ttl_for_same_query`: una
  segunda request idéntica (mismo `q`/`type`, página 1) dentro del TTL NO
  vuelve a disparar fan-out (mocks de `_ingest_*` llamados una sola vez).
- `test_search_fallback_page1_different_item_type_fires_separately`: con
  ambos tipos (`movie`/`series`) sembrados con página llena (`limit=1`) para
  el mismo `q`, cada `type` dispara fan-out por separado — confirma que la
  caché está scoped por tipo, no solo por texto.
- `test_search_fallback_page_gt1_still_fires_when_incomplete_after_page1_cached`:
  tras una request de página 1 (que marca la caché), una request de página 2
  con resultados incompletos sigue disparando fan-out igual que antes —
  regresión explícita de que la caché nunca suprime el disparo de una
  página incompleta.

`bash init.sh` verde: 991 tests, ruff check y format OK. No se hizo commit
(pendiente de confirmación del usuario).
