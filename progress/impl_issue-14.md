# Implementación — Issue #14 (search fan-out completeness)

Rama: `fix/issue-14-search-fanout-completeness`

## Resumen

El fan-out de `/v1/search` a APIs externas solo disparaba con `total == 0`
resultados locales y solo ingeria el top-1 hit por fuente (top-5 para
games). Se cambió el trigger a "página local incompleta" (`len(results) <
limit`, cubre `total == 0` y cualquier página parcial, incluida la página 1)
y la ingestión pasó de "fetch uno, upsert uno" a "fetch una página completa,
upsert cada hit", con la página externa derivada de forma determinista desde
`page`/`limit` de la request — sin cursor ni tabla de estado nuevo.

## Archivos modificados

### Código de producción

- `backlogg/search/service.py` — reescrito:
  - Fast path: `if total > 0 or q is None` → `if len(results) >= limit or q is None`.
  - `_FANOUT_LIMIT` (5) → `_FANOUT_PAGE_SIZE` (20, constante única: tamaño de
    página de TMDB y `limit` pedido a OL/IGDB).
  - Nueva función `_external_page(page, limit)`: `offset = (page-1)*limit`,
    `external_page = offset // _FANOUT_PAGE_SIZE + 1`.
  - `_ingest_movies/_ingest_series/_ingest_books/_ingest_games` pasan de
    `(q)` a `(q, page, limit)`; las 3 primeras dejaron de hacer "fetch
    top-1 + upsert 1" y ahora hacen loop sobre TODOS los resultados de la
    página externa mapeada, con `db.begin_nested()` (savepoint) por ítem —
    replicando el patrón que ya tenía `_ingest_games`.
  - `SearchService.search()`: las 4 llamadas al fan-out ahora pasan
    `page`/`limit` de la request.
- `backlogg/movies/adapters/tmdb.py` — `search_movie(query, year=None, page=1)`
  devuelve `list[dict]` (la página completa de `results`) en vez de
  `dict | None` (`results[0]`). Firma retrocompatible (nuevo parámetro al
  final, con default).
- `backlogg/series/adapters/tmdb.py` — mismo cambio en `search_series(query, page=1)`.
- `backlogg/books/adapters/open_library.py` — `search_book(title, page=1, limit=1)`
  devuelve `list[dict]` (`docs`); default `limit=1` preserva el
  comportamiento de "solo el top hit" para el fallback on-demand de
  `books/service.py`. Se le aplicó el decorator `_ol_search_retry` ya
  existente en el módulo (antes solo se usaba en `_fetch_popular_page`).
- `backlogg/games/adapters/igdb.py` — `search_games(query, limit=5, offset=0)`
  añade `offset` (mismo patrón `offset N;` de `get_top_games`). Se añadió
  `tenacity` (import nuevo en el módulo) con `_igdb_retry` siguiendo
  exactamente el patrón de `_tmdb_retry` (retry solo en 429/5xx/timeout/
  transport error, nunca 4xx, `stop_after_attempt(3)`, backoff exponencial),
  aplicado únicamente a `search_games`.
- `backlogg/search/repository.py` — `SearchRepository.search()`: añadido
  `CatalogSearchEntry.id` como clave de `ORDER BY` secundaria en ambas ramas
  (con/sin `q`), para estabilidad de paginación cuando se insertan filas
  entre requests de páginas consecutivas.
- `backlogg/search/routes.py` — `description=` del route, docstring del
  endpoint (params + párrafo final): reflejan el nuevo trigger ("página
  incompleta", no solo cero resultados) y que se ingesta más de un hit.
- `docs/api.md` — párrafo inglés del fallback (~línea 57-60, añadido) y
  párrafo español "External fallback" (~línea 82-92): "servido desde local
  = no consume cupo" → "página completamente poblada en local = no consume
  cupo"; una página parcialmente poblada consume cupo.
- `backlogg/movies/service.py`, `backlogg/series/service.py`,
  `backlogg/books/service.py` — los 3 call sites del fallback on-demand
  (`get_movie`/`get_series`/`get_book`) ahora toman `search_results[0] if
  search_results else None`, ya que `search_movie`/`search_series`/
  `search_book` devuelven lista en vez de `dict | None`. Sin cambio de
  comportamiento (siguen usando solo el top hit).

### Tests

- `tests/test_search.py`:
  - Nueva fixture autouse `_no_real_fanout_by_default` (parchea los 4
    `_ingest_*` + `refresh_catalog_search` con no-ops por defecto) — el
    nuevo trigger ("página incompleta") hace que la mayoría de fixtures del
    módulo (que siembran muchas menos filas que el `limit` por defecto, 20)
    dispararían fan-out real contra TMDB/Open Library/IGDB si no se
    mockean; los tests que sí quieren ejercer el fallback siguen
    sobreescribiendo estos mismos targets en un `with patch(...)` anidado,
    que tiene precedencia durante su bloque.
  - `test_search_fallback_not_fired_when_local_results_exist`: ahora usa
    `&limit=1` (coincide con la única fila sembrada) para seguir probando
    "página completa ⇒ no fan-out".
  - `test_search_pagination`: mockea los 4 ingests + refresh (antes no
    mockeaba nada; con el nuevo trigger dispararía fan-out real).
  - Nuevo: `test_search_fallback_fires_when_local_page_incomplete` — con
    `total > 0` pero `len(results) < limit`, el fan-out debe dispararse
    (regresión directa del issue #14).
  - Nuevo: `test_search_fallback_page_2_maps_to_external_page`,
    `test_search_fallback_page_3_maps_to_external_page_2` — verifican el
    mapeo `page`/`limit` → `external_page`.
  - Actualizadas las firmas de los `fake_ingest_movies`/`ok_series_ingest`/
    etc. definidos a mano de `(q)` a `(q, page, limit)`.
- `tests/test_search_fanout_ingestion.py` (nuevo archivo) — 4 tests
  unitarios que llaman directamente a `_ingest_movies`/`_ingest_series`/
  `_ingest_books`/`_ingest_games` con los adapters mockeados devolviendo 2
  hits cada uno, verificando que ambos se persisten (no solo el top-1).
  Separado de `test_search.py` porque su fixture autouse reemplazaría estas
  mismas funciones por no-ops.
- `tests/test_search_rate_limit.py`:
  - `test_search_with_local_results_does_not_consume_quota`: `&limit=1`
    para seguir probando "página completa ⇒ no consume cupo".
  - Nuevo: `test_search_with_partial_local_page_does_consume_quota` —
    página parcial (1 resultado local, limit por defecto 20) SÍ consume
    cupo y dispara 429 tras superar el límite.
- `tests/test_search_optional_filters.py` — firmas de `fake_ingest_movies(q)`
  actualizadas a `(q, page, limit)` (2 ocurrencias).
- `tests/test_metrics.py` — `test_search_fanout_increments_external_counter`:
  `search_movie` mockeado ahora devuelve `[]` en vez de `None` (contrato
  nuevo del adapter) y la llamada a `_ingest_movies` pasa `page=1, limit=20`.
- `tests/movies/test_service.py`, `tests/series/test_service.py`,
  `tests/books/test_service.py`, `tests/books/test_service_authors.py` —
  los mocks de `search_movie`/`search_series`/`search_book` que devolvían
  un dict (`{"id": ...}` / `search_doc`) ahora devuelven una lista
  (`[{"id": ...}]` / `[search_doc]`), consistente con el nuevo tipo de
  retorno de los adapters.
- `tests/movies/test_tmdb_adapter.py`, `tests/series/test_tmdb_adapter.py`
  — 3 tests nuevos cada uno: `search_movie`/`search_series` devuelven la
  lista completa (no solo el top hit), devuelven `[]` sin matches, y
  reenvían el parámetro `page`.
- `tests/books/test_open_library_adapter.py` — 5 tests nuevos:
  `search_book` devuelve lista completa, `[]` sin matches, default
  `limit=1` (compat con el fallback on-demand), retry en 5xx transitorio
  (vía `_ol_search_retry`), raise inmediato en 403 (sin retry).
  Corrección de conflicto de nombre de argumento `headers` en los `fake_get`
  planos que patchean `httpx.AsyncClient.get` directamente (`*args,
  **kwargs` en vez de parámetros nombrados — el patch de un método de clase
  con una función plana la vincula como método, así que el primer
  posicional recibido es la instancia de `AsyncClient`, no la URL).
- `tests/games/test_igdb_client.py` — 3 tests nuevos: `search_games`
  reenvía `offset` en el cuerpo de la query IGDB, retry en 5xx transitorio,
  raise inmediato en 4xx no reintentable.

## Decisiones de diseño

- **`_FANOUT_PAGE_SIZE` único**: TMDB tiene tamaño de página fijo (~20,
  nativo, no configurable), así que se reutiliza ese mismo número como
  `limit` pedido a Open Library e IGDB por cada fan-out, de forma que las 4
  fuentes avanzan en páginas de tamaño equivalente.
- **Sin cursor persistido**: el mapeo `page`/`limit` → `external_page` es
  puro y determinista (`(page-1)*limit // _FANOUT_PAGE_SIZE + 1`), tal
  como pedía el plan — reintentar la misma página local siempre vuelve a
  pedir la misma página externa, y el upsert idempotente hace ese re-fetch
  inofensivo.
- **Autouse fixture en `tests/test_search.py`**: necesaria porque el nuevo
  trigger («página incompleta» en vez de «cero resultados») hace que casi
  cualquier fixture con pocas filas dispare fan-out real si no se mockea
  explícitamente — antes bastaba con que hubiera *algún* resultado local
  para tomar el fast path. Sin este guard, varios tests hacían llamadas de
  red reales a TMDB/Open Library/IGDB y comprometían filas reales a través
  de `async_session_factory` (el engine real, que no participa del
  rollback por-test de la fixture `db`), contaminando tests posteriores
  dentro de la misma sesión de pytest. Se descubrió exactamente así durante
  la primera pasada de `bash init.sh` (18 tests fallando por datos
  filtrados desde TMDB real, p.ej. "Inception and Philosophy").

## `bash init.sh` — resultado final

```
── 4. Lint (ruff) ──────────────────────────────────────
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
979 passed in 28.09s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

979 tests totales (957 antes + 22 nuevos netos: tests nuevos añadidos menos
alguna reorganización de tests existentes en el mismo archivo).

## No tocado (según instrucciones)

- `apps/web/**` — el working tree ya traía un cambio sin commitear en
  `apps/web/src/lib/search.ts` (`SEARCH_PAGE_SIZE` 24 → 12) hecho por el
  leader antes de esta sesión; no lo toqué ni lo reverti.
- `RATE_LIMIT_SEARCH_FALLBACK` — sin cambios.
- Ninguna tabla/cursor de estado persistido nuevo.

## Pendiente para el reviewer

- No marqué el issue #14 como `resolved` en `issues_list.json` — corresponde
  al leader tras la revisión, según el protocolo.

## Fix tras CHANGES_REQUESTED (ver `progress/review_issue-14.md`)

El reviewer detectó que `tests/test_search_optional_filters.py` no replicaba
el guard de `tests/test_search.py`: `test_search_with_q_and_date_range_filters_combined`
y `test_search_with_q_and_rating_external_range_filters_combined` golpeaban
`/v1/search?q=...` con el `limit` por defecto (20) pero solo 1 fila local
pasaba el filtro, disparando fan-out real (confirmado con spy por el
reviewer: `_ingest_movies` invocado con argumentos reales).

Fix aplicado: se añadió a `tests/test_search_optional_filters.py` una
fixture autouse `_no_real_fanout_by_default`, idéntica en propósito a la
homónima de `tests/test_search.py` (parchea los 4 `_ingest_*` +
`refresh_catalog_search` con no-ops por defecto; los tests que ya
sobreescribían estos mismos targets en un `with patch(...)` anidado —p.ej.
`test_search_fanout_requery_reapplies_date_filter`— siguen teniendo
precedencia durante su bloque, sin cambios). Se prefirió la fixture autouse
sobre mocks locales en los dos tests señalados porque protege también a
cualquier test futuro del mismo archivo que olvide mockear el fan-out.

Verificación: además de `bash init.sh` en verde (979 passed), se instrumentó
ad-hoc (sin comitear) `backlogg.search.service._tmdb_movies.search_movie`
para lanzar `AssertionError` si se invoca de verdad, vía una fixture
temporal en `tests/conftest.py` (revertida tras la verificación, `git diff`
confirma cero cambios en `tests/conftest.py`). Se corrieron primero los dos
tests señalados en aislamiento y luego la suite completa (979 tests) con
ese spy activo: ningún test disparó la llamada real, confirmando que el
fan-out queda mockeado en todos los casos.

### `bash init.sh` — resultado tras el fix

```
── 4. Lint (ruff) ──────────────────────────────────────
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
979 passed in 26.62s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
