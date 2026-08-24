# Review — feature issue-14: search fan-out completeness

**Veredicto:** CHANGES_REQUESTED

## Resumen

La lógica central del fix (nuevo trigger "página incompleta", mapeo
`page`/`limit` → `external_page`, ingestión de todos los hits en vez de
solo el top-1, contrato `list[dict]` de los adapters, retries, tiebreaker
de `id`, docs) está bien implementada y verificada línea a línea contra
`main`. `bash init.sh` termina en verde con 979 tests. Sin embargo, se
encontró un problema de aislamiento de tests **crítico y confirmado
reproduciblemente**: dos tests en `tests/test_search_optional_filters.py`
disparan fan-out real (llamadas HTTP reales a TMDB/Open Library/IGDB) sin
mockear los `_ingest_*`, exactamente el mismo problema que el propio
implementer identificó y corrigió en `tests/test_search.py` vía la fixture
`_no_real_fanout_by_default` — pero no lo replicó en este otro archivo.

## Verificación detallada

1. **Mapeo `_external_page()`** (`backlogg/search/service.py:59-68`) —
   correcto: `offset = (page-1)*limit; external_page = offset //
   _FANOUT_PAGE_SIZE + 1`. Verificado con los casos de test
   (`page=2,limit=10→1`, `page=3,limit=10→2`) y se pasa consistentemente a
   `search_movie(page=)`, `search_series(page=)`, `search_book(page=,
   limit=_FANOUT_PAGE_SIZE)`, `search_games(limit=_FANOUT_PAGE_SIZE,
   offset=(external_page-1)*_FANOUT_PAGE_SIZE)`. OK.

2. **Contrato roto de los adapters** — `search_movie`/`search_series`/
   `search_book` devuelven `list[dict]`. Los 3 call sites reales del
   fallback on-demand (`backlogg/movies/service.py:184`,
   `backlogg/series/service.py:184`, `backlogg/books/service.py:167`) se
   actualizaron correctamente a `results[0] if results else None`, sin
   cambio de comportamiento observable. OK.

3. **`search_book(title, page=1, limit=1)`** — el default `limit=1`
   preserva el comportamiento previo del fallback on-demand de books
   (`backlogg/books/adapters/open_library.py:159-186`). OK.

4. **Retries nuevos** — `_igdb_retry`
   (`backlogg/games/adapters/igdb.py:20-40`) sigue exactamente el patrón de
   `_tmdb_retry`: retry solo en `{429,500,502,503,504}` +
   `TimeoutException`/`TransportError`, `reraise=True`, nunca 4xx. El
   decorator `_ol_search_retry` ya existente se aplicó a `search_book` sin
   cambios en su criterio de retry. OK.

5. **Aislamiento de tests — CRÍTICO, FALLA.** Ver sección siguiente.

6. **Tiebreaker de `id`** (`backlogg/search/repository.py:77-97`) —
   añadido en ambas ramas del `ORDER BY` (con `q`: `desc(rank_expr),
   CatalogSearchEntry.id`; sin `q`:
   `CatalogSearchEntry.rating_external.desc().nulls_last(),
   CatalogSearchEntry.id`). OK.

7. **Docs** — `docs/api.md` (párrafo inglés ~L59-64 y español "External
   fallback" ~L88-104) y los 3 sitios de `backlogg/search/routes.py`
   (`description=`, docstring params, párrafo final) reflejan
   consistentemente el nuevo trigger y la ingesta de todos los hits. OK.

8. **`RATE_LIMIT_SEARCH_FALLBACK`** — sin cambios (`git diff main --
   backlogg/core/config.py backlogg/core/rate_limit.py` vacío). OK.

9. **Convenciones y arquitectura** — separación de capas respetada
   (`routes.py` sin lógica, `service.py` sin queries SQL, `repository.py`
   como única frontera SQLAlchemy). `AsyncSession` usada correctamente.
   Async route handlers intactos. No hay `print()` ni TODOs sin contexto
   en el diff. Fechas no tocadas por este fix (sin regresión).

## Hallazgo crítico: fan-out real sin mockear en `tests/test_search_optional_filters.py`

El propio informe de implementación (`progress/impl_issue-14.md`) documenta
que el nuevo trigger ("página incompleta" en vez de "cero resultados")
hace que **cualquier test que golpee `/v1/search?q=...` sin mockear los 4
`_ingest_*` dispara fan-out real** contra TMDB/Open Library/IGDB, porque
casi ningún fixture siembra ≥ `limit` (20 por defecto) filas. El
implementer corrigió esto en `tests/test_search.py` con la fixture autouse
`_no_real_fanout_by_default`, pero **no aplicó la misma protección (ni
mocks locales) en `tests/test_search_optional_filters.py`**, que no tiene
ningún autouse ni conftest que mockee los ingests.

Dos tests de ese archivo golpean el endpoint con `q` presente y sin
mockear:

- `test_search_with_q_and_date_range_filters_combined`
  (`tests/test_search_optional_filters.py:118-129`) — `GET
  /v1/search?q=Sof+Q+Combo&date_from=...&date_to=...` sin `limit`
  explícito (default 20). Solo 1 de las 2 filas sembradas cae dentro del
  rango de fecha, así que `len(results) < limit` ⇒ fan-out se dispara.
- `test_search_with_q_and_rating_external_range_filters_combined`
  (`tests/test_search_optional_filters.py:131-146`) — mismo patrón con
  `rating_external_min`/`rating_external_max`.

**Confirmado reproduciblemente**: instrumenté ambos tests con un spy sobre
`backlogg.search.service._ingest_movies` (sin tocar el código de
producción) y en los dos casos `_ingest_movies` se invoca de verdad con
argumentos reales (`call('Sof Q Combo', 1, 20)` / `call('Sof Q Rating', 1,
20)`), es decir intenta una llamada HTTP real a TMDB. En este sandbox pasan
"por accidente" porque no hay acceso de red y la excepción de
`_ingest_movies` se traga silenciosamente (`except Exception:
logger.exception(...)`), dejando el resultado observable sin cambios — por
eso `bash init.sh` no lo detecta. Pero en cualquier entorno con acceso a
internet (CI real de GitHub Actions, laptop de un dev) estos dos tests:

- Hacen llamadas HTTP reales a TMDB/Open Library/IGDB (consumo de cuota de
  API real, latencia y flakiness de red en el pipeline de tests).
- Si la llamada externa tiene éxito, comprometen filas reales en
  `TEST_DATABASE_URL` a través de `async_session_factory`, que **no**
  participa del rollback por-test de la fixture `db` (mismo mecanismo que
  ya documentó el implementer para `test_search.py`), contaminando tests
  posteriores dentro de la misma sesión de `pytest`.

Esto es exactamente el tipo de bug que el protocolo de esta revisión marca
como "crítico, no cosmético" — un test suite que a veces pega contra APIs
externas reales y escribe en la DB real.

## Cambios requeridos

1. En `tests/test_search_optional_filters.py`, mockear los 4 `_ingest_*` +
   `refresh_catalog_search` (siguiendo el mismo patrón usado en las demás
   pruebas de ese mismo archivo, p. ej.
   `test_search_fanout_requery_reapplies_date_filter`) en:
   - `test_search_with_q_and_date_range_filters_combined`
     (línea 118)
   - `test_search_with_q_and_rating_external_range_filters_combined`
     (línea 131)

   Alternativamente, añadir una fixture autouse equivalente a
   `_no_real_fanout_by_default` de `tests/test_search.py` a este archivo
   (o extraerla a `tests/conftest.py` si aplica a más módulos), para que
   ningún test futuro en este archivo pueda repetir el mismo error por
   omisión.

2. Tras el fix, re-ejecutar `bash init.sh` y confirmar 0 llamadas de red
   reales durante la suite (puede verificarse con el mismo patrón de spy
   usado en esta revisión, o revisando que ambos tests pasen incluso con
   la red deshabilitada explícitamente).

## Checkpoints

- C1: [x] `bash init.sh` termina sin errores.
- C2: [x] Sin `print()` de debug en el código nuevo.
- C3: [x] Sin TODOs sin contexto.
- C4: [x] `ruff check` / `ruff format --check` pasan.
- C5: [x] Todos los tests pasan (verde en este entorno) — pero ver hallazgo
  crítico: el verde es engañoso porque dos tests dependen de que la
  llamada de red real falle silenciosamente; no son deterministas ni
  aislados. No se marca `[ ]` formalmente porque `pytest` sí terminó en
  verde, pero el hallazgo crítico anterior es motivo de rechazo por sí
  solo (regla dura: "un test suite que a veces pega contra APIs externas
  reales... es un bug serio de aislamiento de tests").
- C9–C13: N/A — no se añade ni modifica la firma del endpoint
  (`GET /v1/search` ya existía; mismo `response_model`, mismos params).
- C14: [x] Sin cambios en conversión de fechas (no tocado por este fix).
- C15: [x] IDs externos de test siguen siendo únicos por test.
- C16/C17: [x] Fallback on-demand de movies/series/books persiste antes de
  devolver y sigue devolviendo 404 si no hay hit externo (sin cambio de
  comportamiento, solo adaptado al nuevo contrato de retorno).
- C20: [x] Sin lógica de negocio en `routes.py`.
- C21: [x] Sin queries SQLAlchemy en `service.py`.
- C22: [x] No se devuelven modelos ORM directamente.

## output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (63 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
283 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
979 passed in 28.40s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Evidencia adicional (fuera de init.sh, reproducida por el reviewer)

Test ad-hoc (no incluido en el repo, solo para diagnóstico) que instrumenta
`backlogg.search.service._ingest_movies` con un spy alrededor de las
llamadas reales hechas por
`test_search_with_q_and_date_range_filters_combined` y
`test_search_with_q_and_rating_external_range_filters_combined`:

```
CALLED: True call('Sof Q Combo', 1, 20)
CALLED: True call('Sof Q Rating', 1, 20)
```

Confirma que ambos tests, tal como están escritos en la rama, disparan
`_ingest_movies` real (que a su vez llamaría a
`TMDBClient.search_movie` — sin mock — contra la red).

---

# Segunda pasada de revisión (post-fix)

**Veredicto:** APPROVED

## Verificación del fix

1. **`progress/impl_issue-14.md`, sección "Fix tras CHANGES_REQUESTED"
   (líneas 184-224)** — describe el fix aplicado: fixture autouse
   `_no_real_fanout_by_default` añadida a
   `tests/test_search_optional_filters.py`, mismo patrón que
   `tests/test_search.py`. Coincide con lo verificado en el diff.

2. **Diff de `tests/test_search_optional_filters.py`** —
   (`tests/test_search_optional_filters.py:30-51`) la fixture es
   `@pytest_asyncio.fixture(autouse=True)`, definida a nivel de módulo (no
   dentro de ninguna clase — el archivo no tiene clases, todos los tests son
   funciones top-level), por lo que aplica a los 13 tests del archivo sin
   excepción. Parchea los 4 `_ingest_*` + `refresh_catalog_search` con
   `AsyncMock(return_value=None)` vía `with (...)` alrededor del `yield`.

   - Los dos tests señalados en la primera pasada
     (`test_search_with_q_and_date_range_filters_combined`,
     `test_search_with_q_and_rating_external_range_filters_combined`,
     líneas 141-166) ahora quedan cubiertos exclusivamente por el autouse
     (no tienen `with patch(...)` local) — correcto, es justo el caso que
     faltaba.
   - Los tests que ya tenían `with patch(...)` anidado sobre los mismos
     targets (`test_search_without_q_ingest_and_refresh_mocks_never_called`,
     `test_search_without_q_does_not_call_enforce_search_fallback`,
     `test_search_fanout_requery_reapplies_date_filter`,
     `test_search_fanout_requery_reapplies_rating_external_filter`) siguen
     funcionando: `unittest.mock.patch` como context manager anidado
     sobreescribe el mismo atributo durante su bloque y restaura el valor
     previo (el mock del autouse) al salir — sin conflicto, confirmado
     porque estos 4 tests siguen pasando y sus asserts sobre
     `mock.assert_not_called()` / sustitución con `fake_ingest_movies` no
     cambiaron de comportamiento.
   - Repasado el resto del archivo: ningún otro test golpea `/v1/search`
     con `q` presente sin protección (los que usan `q=` son solo los 6
     mencionados arriba; el resto omite `q` o espera 422 antes de llegar al
     fan-out).

3. **Verificación independiente de red (no solo el reporte del
   implementer)** — instrumenté `backlogg.movies.adapters.tmdb.TMDBClient.search_movie`
   (vía parche temporal en `tests/conftest.py`, revertido tras la
   verificación — `git diff --stat -- tests/conftest.py` confirma cero
   cambios) para lanzar `AssertionError` si se invoca de verdad:
   - Corridos en aislamiento los dos tests antes señalados: **2 passed**,
     sin disparar el `AssertionError` ⇒ no hay llamada real a TMDB.
   - Corrido el módulo completo (`tests/test_search_optional_filters.py`,
     13 tests) con el mismo spy activo: **13 passed**, ningún test dispara
     la llamada real.

4. **`bash init.sh`** — verde: `979 passed`, `ruff check`/`ruff format`
   OK, tras revertir el spy temporal de `tests/conftest.py`.

5. **Alcance del diff de producción** — `git diff main -- backlogg/`
   sigue teniendo las mismas 543 líneas de diff ya revisadas en la primera
   pasada (contrato `list[dict]` de adapters, `_external_page`, retries,
   tiebreaker, docs). Confirmado por timestamps de mtime de los archivos en
   `git status --porcelain`: `tests/test_search_optional_filters.py` es,
   con diferencia, el archivo modificado más recientemente (mtime muy
   posterior a todos los `backlogg/*.py`), consistente con que el fix solo
   tocó ese archivo de test. Ningún archivo de `backlogg/` cambió en esta
   segunda pasada.

## Checkpoints (actualización)

- C5: [x] Todos los tests pasan de forma determinista y aislada — el
  hallazgo crítico de la primera pasada queda resuelto; verificado con spy
  propio, no solo con el reporte del implementer.

## Conclusión

El único motivo de rechazo de la primera pasada (aislamiento de tests /
riesgo de llamadas HTTP reales en `tests/test_search_optional_filters.py`)
queda resuelto y verificado de forma independiente. No hay cambios de
producción adicionales. `bash init.sh` termina en verde. Se aprueba la
feature.

---

# Tercera pasada de revisión (fix de rendimiento)

**Veredicto:** APPROVED

## Contexto

QA manual detectó que el fan-out (ya aprobado en las dos pasadas anteriores)
hacía hasta 20 llamadas HTTP secuenciales de detalle por fuente dentro de la
misma request, sin importar que `limit` fuera mucho menor. El implementer
acotó el trabajo caro a `limit` y paralelizó las llamadas de detalle bajo un
semáforo, manteniendo la fase de persistencia en DB secuencial.

## Verificación detallada

1. **Cap a `limit` antes de la fase cara** — confirmado en las 4 funciones
   (`backlogg/search/service.py`):
   - `_ingest_movies:102` — `candidates = [raw.get("id") for raw in
     results[:limit] if raw.get("id")]`, calculado sobre `results` ya
     obtenidos con `search_movie(q, page=external_page)` (sin tocar
     `_FANOUT_PAGE_SIZE=20` en la llamada externa, línea 98).
   - `_ingest_series:161` — mismo patrón.
   - `_ingest_books:228-229` — `results = await
     _ol_client.search_book(q, page=external_page, limit=_FANOUT_PAGE_SIZE)`
     (llamada externa intacta, sigue pidiendo 20), luego `candidates =
     results[:limit]`.
   - `_ingest_games:275-278` — `search_games(q, limit=_FANOUT_PAGE_SIZE,
     offset=offset)` intacto; `results = results[:limit]` aplicado antes del
     loop de upsert (games no tiene fase de detail-fetch separada — el
     `search` bulk de IGDB ya trae los datos completos — así que el cap se
     aplica directamente sobre lo único caro, el upsert en DB).
   - `_external_page()` (líneas 67-76) no se tocó: mismo cálculo determinista
     `offset // _FANOUT_PAGE_SIZE + 1` de las pasadas anteriores.

2. **Separación red/DB** — `_fetch_movie_detail`/`_fetch_series_detail`/
   `_fetch_book_detail` (líneas 79-90, 141-152, 198-220) solo llaman a los
   clientes HTTP de módulo (`_tmdb_movies`, `_tmdb_series`, `_ol_client`); no
   reciben ni tocan `AsyncSession` en ningún punto. El `asyncio.gather(...,
   return_exceptions=True)` que las ejecuta en paralelo (líneas 106-109,
   164-167, 232-235) es puramente de red. La fase de persistencia
   (`async with async_session_factory() as db: async with db.begin(): ...
   db.begin_nested()` por ítem) se abre **después** de que `gather` retorna,
   y el loop `for ... in zip(candidates, details/fetched, strict=True)` es
   estrictamente secuencial — una sola `AsyncSession` nunca se usa desde más
   de una corutina a la vez. Correcto: evita el bug real de escritura
   concurrente sobre `AsyncSession`.

3. **Semáforo de concurrencia** — `_DETAIL_FETCH_CONCURRENCY = 5`
   (línea 64); cada helper (`_fetch_*_detail`) adquiere `async with sem:`
   envolviendo únicamente su propia llamada HTTP individual (líneas 81, 143,
   211), no un bloque que cubra todo el `gather`. Con esto, como mucho 5
   llamadas de detalle están en vuelo a la vez sin importar cuántos
   `candidates` haya (hasta `limit`, p. ej. 12). Verificado también por
   `test_ingest_movies_detail_fetches_run_concurrently` /
   `test_ingest_series_detail_fetches_run_concurrently`, que usan un contador
   de solapamiento real (no solo verifican que se llamó a `gather`).

4. **Manejo de errores preservado** — `return_exceptions=True` presente en
   los 3 `gather` de fase de red (líneas 108, 166, 234) y en el `gather`
   externo de `SearchService.search()` (línea 365, sin cambios). Cada
   `_fetch_*_detail` ya captura `Exception` internamente y hace
   `logger.exception(...)` con los mismos parámetros/formato que las pasadas
   anteriores; el loop de persistencia añade una capa defensiva adicional
   (`isinstance(outcome, BaseException)` con `logger.exception(...,
   exc_info=outcome)` — correcto usar `exc_info=` explícito aquí porque no
   hay excepción activa en ese punto del control de flujo) para el caso
   límite de una excepción no capturada internamente. Confirmado con
   `test_ingest_movies_one_detail_fetch_failure_does_not_abort_others`: un
   `RuntimeError` simulado en el detail-fetch de un ítem no impide que el
   otro se persista.

5. **Tests nuevos** (`tests/test_search_fanout_ingestion.py`, 7 tests
   nuevos, 11 en total) — revisados uno a uno:
   - `test_ingest_{movies,series,books}_caps_detail_fetches_to_limit` /
     `test_ingest_games_caps_upserts_to_limit` — con 3 hits disponibles y
     `limit=2`, verifican tanto que solo se invocan los detail-fetches/
     upserts esperados (`called_ids`) como que el tercer ítem **no** queda
     persistido en DB. Prueban el cap real, no solo el valor de retorno.
   - `test_ingest_{movies,series}_detail_fetches_run_concurrently` — usan un
     contador `concurrent`/`max_concurrent` con `asyncio.sleep(0.05)` dentro
     del fake de detalle; `assert max_concurrent >= 2` es evidencia real de
     solapamiento en tiempo, no solo de que se llamó a `asyncio.gather`. No
     hay test equivalente para books, pero el helper
     (`_fetch_book_detail`) sigue exactamente el mismo patrón estructural
     verificado en movies/series (semáforo envolviendo únicamente la llamada
     de red) — gap menor, no bloqueante.
   - `test_ingest_movies_one_detail_fetch_failure_does_not_abort_others` —
     cubre el punto 4.
   - Los 4 tests preexistentes (`test_ingest_*_upserts_all_hits_from_search_page`)
     siguen intactos y siguen pasando con la nueva implementación paralela
     (usan `limit=20` con solo 2 hits disponibles, por debajo del cap, así
     que no interfieren con la nueva lógica de recorte).
   - Aislamiento correcto: todos parchean `async_session_factory` para que
     apunte a la fixture `db` (rollback por test) y mockean los métodos de
     los clientes HTTP directamente — no hay red real ni escritura fuera de
     la transacción de test, siguiendo el mismo patrón ya validado en las
     dos pasadas anteriores para este archivo.

6. **`bash init.sh`** — verde: `986 passed` (979 + 7 nuevos, coincide con lo
   reportado), `ruff check`/`ruff format` OK. Ver output completo abajo.

7. **Alcance del diff** — `git diff main --stat -- backlogg/ tests/ docs/`
   sigue mostrando exactamente los mismos 23 archivos ya revisados en las
   pasadas anteriores (incluyendo el nuevo `tests/test_search_fanout_ingestion.py`,
   untracked, no listado por `git diff` pero verificado por separado). Los
   recuentos de líneas de `tests/test_search.py` (158),
   `tests/test_search_optional_filters.py` (27) y `tests/test_search_rate_limit.py`
   (34) no cambiaron respecto al reporte de la segunda pasada, confirmando
   que el fix de rendimiento no tocó esos archivos. `backlogg/search/repository.py`
   (16 líneas) tampoco cambió. El único archivo de producción con diff
   adicional es `backlogg/search/service.py`; `backlogg/search/routes.py` y
   `docs/api.md` solo tienen los ajustes de docstring/documentación
   esperados (confirmados con `git diff main -- backlogg/search/routes.py
   docs/api.md`, ambos consistentes con "hasta `limit` hits" y "acotadas a 5
   peticiones concurrentes").

## Observación no bloqueante

`progress/impl_issue-14.md` no se actualizó con una sección que documente
este tercer cambio (a diferencia del "Fix tras CHANGES_REQUESTED" que sí
documenta el fix de la segunda pasada). No afecta la corrección del código
ni de los tests, pero conviene añadir esa sección para mantener la
trazabilidad completa de la feature antes de cerrar el issue.

## Checkpoints (sin cambios respecto a la segunda pasada)

- C1: [x] `bash init.sh` termina sin errores.
- C2: [x] Sin `print()` de debug.
- C3: [x] Sin TODOs sin contexto.
- C4: [x] `ruff check` / `ruff format --check` pasan.
- C5: [x] Todos los tests pasan de forma determinista (986).
- C9–C13: N/A.
- C14: [x] Sin cambios en conversión de fechas.
- C15: [x] IDs externos de test siguen siendo únicos por test.
- C16/C17: [x] Sin cambios respecto a las pasadas anteriores.
- C20: [x] Sin lógica de negocio en `routes.py`.
- C21: [x] Sin queries SQLAlchemy en `service.py` (persistencia sigue
  delegada a `*_repo.upsert_*`/`upsert_external_id`).
- C22: [x] No se devuelven modelos ORM directamente.

## output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (63 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
283 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
986 passed in 26.84s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Conclusión

El fix de rendimiento es correcto: acota el trabajo caro (detail-fetch/
upsert) a `limit` sin desalinear `_external_page()`, paraleliza únicamente
la fase de red bajo un semáforo acotado (5), mantiene la fase de
persistencia estrictamente secuencial sobre una única `AsyncSession` (sin el
bug real de escritura concurrente), y preserva el manejo de errores
por-ítem ya aprobado. Los 7 tests nuevos prueban el cap y la concurrencia
con evidencia real (no solo mocks de `asyncio.gather`), y el aislamiento de
fallos. `bash init.sh` termina en verde (986 tests). Se aprueba el fix; la
única observación es no bloqueante (actualizar `progress/impl_issue-14.md`
con una sección para esta tercera pasada).

---

# Cuarta pasada de revisión (rating tiebreaker)

**Veredicto:** APPROVED

## Contexto

QA manual: en resultados de búsqueda con texto, ítems empatados en `ts_rank`
(coincidencia exacta de título corto) se desempataban por `id` (orden de
inserción), sin relación con qué tan conocido es el ítem. El implementer
insertó `CatalogSearchEntry.rating_external.desc().nulls_last()` como clave
intermedia del `ORDER BY`, entre `desc(rank_expr)` e `id`, únicamente en la
rama `if q is not None:` de `SearchRepository.search()`.

## Verificación detallada

1. **Cambio exacto en `backlogg/search/repository.py:88-96`** — el `ORDER BY`
   de la rama `q is not None` queda:
   ```
   desc(rank_expr),
   CatalogSearchEntry.rating_external.desc().nulls_last(),
   CatalogSearchEntry.id,
   ```
   en ese orden exacto. Confirmado por lectura directa del archivo.

2. **Rama `else` (sin `q`) no tocada por este cambio** — `git diff main --
   backlogg/search/repository.py` muestra que el `id` en la rama `else`
   (líneas 98-105) ya se había añadido en la **primera pasada** (tiebreaker
   de paginación, checkpoint C del review original: "añadido en ambas ramas
   del `ORDER BY`"), no en este cambio nuevo. Aislé el diff de este cambio
   puntual con `git stash push -- backlogg/search/repository.py` y reejecuté
   el test nuevo contra el `repository.py` del estado previamente aprobado
   (pass 3): el test falla (`assert 1 < 0`), confirmando que el único delta
   real de esta pasada es la inserción de la clave `rating_external` en la
   rama `q is not None` — la rama `else` sigue siendo
   `rating_external.desc().nulls_last(), id`, sin cambios respecto a lo ya
   aprobado. Correcto.

3. **Docstring actualizado** (`backlogg/search/repository.py:41-53`) —
   describe correctamente el nuevo orden de criterios (`ts_rank` → `rating_external`
   desc nulls-last → `id`) y por qué (issue #14 / desempates por relevancia
   similar).

4. **El test fuerza un empate real, no artificial** — `tied_rank_seeded_db`
   (`tests/test_search.py:696-721`) siembra dos películas con `title` y
   `original_title` idénticos (`"The Great Adventure"`), por lo que
   `ts_rank(search_vector, plainto_tsquery('simple', 'The Great Adventure'))`
   es idéntico para ambas filas — es la forma más simple y fiable de
   garantizar el empate (no depende de heurísticas de `ts_rank` con textos
   distintos que podrían no empatar de verdad).
   - Orden de inserción: primero el ítem de rating bajo
     (`obscure-remake-1999-search-test`, `rating_external=2.1`), luego el de
     rating alto (`famous-original-2010-search-test`, `rating_external=9.1`)
     — es decir, el `id` autoincremental del obscuro es menor que el del
     famoso, así que un desempate ingenuo por `id ASC` (o incluso por `id`
     como único criterio sin `rating_external` de por medio) pondría el
     obscuro primero.
   - **Confirmado que el test falla sin el fix**: revertí temporalmente
     `backlogg/search/repository.py` a su estado del pass 3 aprobado (vía
     `git stash`, con el `tests/test_search.py` nuevo intacto) y corrí
     `test_search_tied_rank_orders_by_rating_external_desc` en aislamiento:
     `FAILED ... assert famous_idx < obscure_idx / assert 1 < 0`. Es una
     regresión real, no un test que "pasaría igual con el código viejo".
     Tras `git stash pop`, restaurado el fix; el test pasa de nuevo (ver
     punto 6).

5. **Aislamiento del test** — la fixture autouse a nivel de módulo
   `_no_real_fanout_by_default` (`tests/test_search.py:106-127`, sin
   `autouse` acotado a ninguna clase, aplica a todas las funciones del
   archivo) mockea los 4 `_ingest_*` + `refresh_catalog_search` con
   no-ops por defecto. El nuevo test no la sobreescribe con `with
   patch(...)` local, así que queda cubierto exclusivamente por el guard
   autouse — sin fan-out real, sin llamadas HTTP, sin escritura fuera de la
   transacción de test (usa la fixture `db` con rollback por-test vía
   `tied_rank_seeded_db(db)`).

6. **`bash init.sh`** — verde: `987 passed` (986 + 1 nuevo, coincide con lo
   reportado), `ruff check`/`ruff format` OK. Ver output completo abajo.

7. **Alcance del diff** — `git diff --stat -- backlogg/ tests/ docs/` sigue
   mostrando exactamente los mismos 23 archivos ya revisados en las tres
   pasadas anteriores; `tests/test_search.py` pasó de 209 a 209+57 líneas
   netas (la nueva sección de tie-break, hunk `@@ -558,6 +684,57 @@`,
   confirmado como adición pura sin tocar código previamente aprobado, salvo
   la firma ya conocida `fake_ingest_movies(q, page, limit)` de la primera
   pasada que aparece en el mismo diff acumulado). `backlogg/search/repository.py`
   pasó de 16 a 28 líneas de diff (docstring + `ORDER BY` de la rama `q`).
   Ningún otro archivo de `backlogg/` o `tests/` tiene cambios adicionales
   respecto al estado ya aprobado en la tercera pasada.

## Checkpoints (actualización)

- C5: [x] Todos los tests pasan de forma determinista y aislada (987),
  incluido el nuevo test de desempate, verificado independientemente como
  regresión real (falla sin el fix, pasa con él).
- C14: [x] Sin cambios en conversión de fechas.
- C20/C21/C22: [x] Sin cambios de capas — el fix vive enteramente en
  `repository.py` (frontera SQLAlchemy), sin tocar `service.py`/`routes.py`.

## output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (63 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
283 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
987 passed in 27.92s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Observación no bloqueante

Igual que en la tercera pasada, `progress/impl_issue-14.md` no se actualizó
con una sección propia para este cuarto cambio (el desempate por
`rating_external`). No afecta la corrección del código ni de los tests.

## Conclusión

El cambio es exactamente el descrito: una única clave intermedia
(`rating_external DESC NULLS LAST`) insertada en el `ORDER BY` de la rama
`q is not None`, reutilizando una señal ya usada en la rama `else` (no es una
señal nueva). La rama `else` no fue tocada por este cambio (el `id` ya
estaba ahí desde la primera pasada). El test nuevo fuerza un empate real
(mismo título exacto) y se confirmó como regresión real revirtiendo el fix
temporalmente. Aislamiento correcto vía la fixture autouse existente.
`bash init.sh` termina en verde (987 tests). Se aprueba el cambio.

---

# Quinta pasada de revisión (rating como criterio principal)

**Veredicto:** APPROVED

## Contexto

QA manual (queries reales vía psql contra `backlogg-db`) confirmó que el
desempate `rating_external` insertado en la cuarta pasada casi nunca se
activaba en la práctica: `ts_rank` rara vez es exactamente igual entre dos
filas con títulos distintos, así que con `ORDER BY desc(rank_expr),
rating_external DESC NULLS LAST, id` el rating nunca llegaba a decidir el
orden real. Ejemplo confirmado en vivo con "batman": un DLC sin valorar
("Batman: Arkham City - Arkham City Skins Pack") quedaba por delante de un
juego con nota 8.6 por solo 0.0001 de diferencia de `ts_rank`. El
implementer invirtió la prioridad: `rating_external DESC NULLS LAST` pasa a
ser la clave PRINCIPAL del `ORDER BY`, `ts_rank` pasa a ser desempate
secundario, `id` sigue como último desempate de estabilidad de paginación.

## Verificación detallada

1. **Cambio exacto en `backlogg/search/repository.py:97-105`** — el
   `ORDER BY` de la rama `q is not None` queda, en este orden exacto:
   ```
   CatalogSearchEntry.rating_external.desc().nulls_last(),
   desc(rank_expr),
   CatalogSearchEntry.id,
   ```
   Confirmado por lectura directa del archivo. La rama `else` (sin `q`,
   líneas 106-114) no fue tocada por este cambio — sigue siendo
   `rating_external.desc().nulls_last(), id`, exactamente como quedó en la
   primera pasada; confirmado revisando el diff acumulado contra `main`
   (`git diff main -- backlogg/search/repository.py`), que no muestra ningún
   `+`/`-` en esa sección.

2. **El `WHERE` de relevancia no cambió** — `search_vector @@
   plainto_tsquery('simple', :q)` (líneas 61-64) es idéntico al de las
   cuatro pasadas anteriores; el diff acumulado contra `main` no toca esa
   sección. Confirmado que este cambio es exclusivamente de `ORDER BY`: qué
   filas hacen match (el conjunto filtrado) no cambia, solo el orden dentro
   de ese conjunto.

3. **Docstring del método** (líneas 42-58) actualizado consistentemente:
   describe `rating_external DESC NULLS LAST` como clave principal, `ts_rank`
   como desempate secundario (incluyendo agrupar NULLs entre sí, ordenados
   por relevancia), `id` como desempate final, y explica explícitamente por
   qué se abandonó el orden anterior ("ts_rank alone is not a reliable
   primary sort key... a rank-first order effectively never lets
   rating_external decide").

4. **El test nuevo prueba el caso real, no un artefacto** —
   `distinct_rank_seeded_db` (`tests/test_search.py:738-771`) siembra
   `"Batman"` (rating 9.0) vs. `"Batman Batman Batman Arkham City Skins
   Pack"` (rating `None`). Verifiqué de forma independiente contra la
   migración 0028 (`_SEARCH_VECTOR_EXPR`, título repetido y no puntuado)
   ejecutando la expresión `ts_rank` real vía `docker exec backlogg-db
   psql -U postgres -d backlogg_test`:
   ```
   rank_single  = 0.075990885  (Batman)
   rank_repeated = 0.09066558  (Batman Batman Batman Arkham City Skins Pack)
   ```
   Confirma el `ts_rank` genuinamente DISTINTO afirmado en el docstring de
   la fixture, con el título repetido efectivamente más alto (no un empate
   accidental).

5. **El test falla con el código de la ronda anterior (regresión real,
   no cosmética)** — reverté temporalmente solo el `ORDER BY` de la rama
   `q is not None` a `desc(rank_expr), rating_external DESC NULLS LAST, id`
   (el estado exacto ya aprobado en la cuarta pasada) dejando el resto del
   archivo y de `tests/test_search.py` intactos, y corrí ambos tests en
   aislamiento:
   ```
   test_search_tied_rank_orders_by_rating_external_desc PASSED
   test_search_distinct_rank_orders_by_rating_external_over_ts_rank FAILED
     assert rated_idx < unrated_idx
     E    assert 1 < 0
   ```
   Confirma que el test nuevo detecta exactamente la regresión reportada en
   QA (con el `ORDER BY` viejo, el ítem de mayor `ts_rank`/sin rating
   quedaba primero). Restaurado el archivo original; ambos tests vuelven a
   pasar (`2 passed`).

6. **`test_search_tied_rank_orders_by_rating_external_desc` sigue siendo
   válido** — mismo título exacto en ambas filas (mismo `ts_rank`), por lo
   que el nuevo orden (`rating_external` como clave principal) produce el
   mismo resultado observable que el desempate anterior (`famous_idx <
   obscure_idx`). Ninguna premisa del test se rompió; sigue verificando lo
   mismo que verificaba antes, solo que ahora por la vía de la clave
   principal en vez de un desempate exacto.

7. **Aislamiento de tests** — ambos tests (`tied_rank_seeded_db`,
   `distinct_rank_seeded_db`, funciones top-level sin clase envolvente) caen
   bajo la fixture autouse de módulo `_no_real_fanout_by_default`
   (`tests/test_search.py:107`, ya validada en la cuarta pasada); ninguno
   la sobreescribe con `with patch(...)` local (`grep` confirma cero
   ocurrencias de `with patch` en el archivo). Sin fan-out real, sin
   llamadas HTTP, sin escritura fuera de la transacción de test (`db` con
   rollback por-test).

8. **`bash init.sh`** — verde: `988 passed` (987 + 1 nuevo, coincide con lo
   reportado), `ruff check`/`ruff format` OK. Ver output completo abajo.

9. **Alcance del diff** — verificado por mtime (`git status --porcelain=v1
   ... | stat`) que `backlogg/search/repository.py`, `tests/test_search.py`
   y `progress/current.md` son, con diferencia, los tres archivos
   modificados más recientemente en el árbol de trabajo (14:51–14:53),
   posteriores incluso a `progress/review_issue-14.md` (14:35, la propia
   cuarta pasada). Todos los demás archivos con diff (`backlogg/search/service.py`,
   `docs/api.md`, adapters, etc.) tienen mtimes anteriores a la cuarta
   pasada y ya fueron revisados y aprobados en pasadas previas. `git diff
   main --stat -- backlogg/search/repository.py tests/test_search.py
   progress/current.md` confirma que estos son los únicos tres archivos con
   cambios de esta quinta pasada acumulados sobre lo ya aprobado.

## Juicio sobre el trade-off (rating domina sobre relevancia textual)

Es una decisión de producto explícita y confirmada dos veces por el
usuario, y el efecto directo (ítems bien valorados por encima de ítems sin
valorar aunque el texto coincida "mejor") es el comportamiento buscado. Un
caso a vigilar, no bloqueante: como el filtro de relevancia (`WHERE
search_vector @@ plainto_tsquery(...)`) indexa tanto `title` como
`overview`, un ítem cuyo único match sea una mención incidental en el
`overview` (coincidencia de texto débil) pero con rating alto podría
superar a un ítem cuyo `title` coincide exactamente pero no tiene rating —
antes ese caso ya era posible en menor medida (rating como desempate de
`ts_rank` exacto), pero ahora es sistemático porque rating es la clave
principal. No es un bug de esta implementación (el `WHERE` ya incluía
`overview` desde antes de esta feature) y no contradice la decisión de
producto, pero si en QA futura aparecen resultados "raros" (un ítem
tangencialmente relacionado por texto de sinopsis apareciendo primero por
tener buena nota), la causa raíz sería esta combinación, no un bug nuevo.

## Checkpoints (actualización)

- C5: [x] Todos los tests pasan de forma determinista y aislada (988),
  incluido el nuevo test, verificado independientemente como regresión real
  (falla con el `ORDER BY` de la ronda anterior, pasa con el actual) y con
  `ts_rank` genuinamente distinto verificado contra la expresión SQL real
  de la migración 0028.
- C14: [x] Sin cambios en conversión de fechas.
- C20/C21/C22: [x] Sin cambios de capas — el fix vive enteramente en
  `repository.py` (frontera SQLAlchemy), sin tocar `service.py`/`routes.py`.

## output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (63 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
283 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
988 passed in 31.16s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Observación no bloqueante

Igual que en la tercera y cuarta pasadas, `progress/impl_issue-14.md` no se
actualizó con una sección propia para este quinto cambio (la inversión de
prioridad rating/ts_rank); la documentación de este cambio vive solo en
`progress/current.md`. No afecta la corrección del código ni de los tests.

## Conclusión

El cambio es exactamente el descrito: se invierte la prioridad entre
`rating_external` y `ts_rank` en el `ORDER BY` de la rama `q is not None`
(`rating_external DESC NULLS LAST` pasa a ser la clave principal, `ts_rank`
el desempate secundario), sin tocar el `WHERE` de relevancia ni la rama
`else`. El test nuevo se verificó de forma independiente en dos frentes: (1)
que el `ts_rank` de las dos filas sembradas es genuinamente distinto,
ejecutando la expresión SQL real de la migración 0028 contra
`backlogg-db`; y (2) que el test falla con el `ORDER BY` de la cuarta
pasada aprobada, confirmando que prueba la regresión real reportada en QA y
no un caso que pasaría igual con el código anterior. El test preexistente
de empate exacto sigue siendo válido. `bash init.sh` termina en verde (988
tests). El alcance del cambio se limita a `backlogg/search/repository.py`,
`tests/test_search.py` y `progress/current.md`, verificado por mtime y por
diff acumulado. Se aprueba el cambio.

---

# Sexta pasada de revisión (fan-out eager en página 1 + caché TTL)

**Veredicto:** APPROVED

## Contexto

QA manual: para queries amplias y populares (p. ej. "final fantasy", 111
coincidencias locales), el trigger de fan-out (`len(results) < limit`)
nunca se disparaba porque siempre había de sobra resultados locales para
llenar cada página, así que ítems conocidos pero ausentes en local nunca se
descubrían salvo con un término exacto y específico que saliera corto en
local. Decisión de producto confirmada: la página 1 de cualquier búsqueda
con texto debe comprobar las APIs externas al menos una vez por TTL,
deduplicado con `core/cache` para no repetir la llamada externa en cada
request idéntica.

## Verificación detallada

1. **Condición de disparo exacta** — confirmado por lectura directa de
   `backlogg/search/service.py:392-400`:
   ```python
   page_incomplete = len(results) < limit
   cache = get_cache()
   fanout_cache_key = _fanout_cache_key(q, item_type) if q is not None else None
   already_checked_recently = (
       fanout_cache_key is not None and cache.get(fanout_cache_key) is not None
   )
   should_fanout = q is not None and (
       page_incomplete or (page == 1 and not already_checked_recently)
   )
   ```
   Es exactamente `q is not None and (page_incomplete or (page == 1 and not
   already_checked_recently))`. Al ser una disyunción (`or`), el caso
   `page_incomplete` nunca puede quedar suprimido por la caché — si
   `page_incomplete` es `True`, `should_fanout` es `True`
   independientemente del valor de `already_checked_recently`. Verificado
   además experimentalmente: revertí temporalmente el bloque completo a
   `should_fanout = q is not None and page_incomplete` (el trigger previo a
   esta sexta pasada) y corrí los 4 tests nuevos/modificados en aislamiento
   — los 4 fallan (`test_search_fallback_page1_fires_first_time_...`,
   `..._not_refired_within_ttl_...`, `..._different_item_type_fires_...`,
   `..._page_gt1_still_fires_...`, todos `FAILED`), confirmando que
   realmente ejercitan la lógica nueva y no un caso que ya pasaría con el
   código anterior. Restaurado el archivo original (`git diff --stat`
   confirma 373 líneas de diff, igual que antes del experimento); `bash
   init.sh` vuelve a dar 991 tests en verde tras restaurar.

2. **Momento de marcado de la caché** — `backlogg/search/service.py:409-418`:
   el `cache.set(fanout_cache_key, True, _FANOUT_QUERY_CACHE_TTL_SECONDS)`
   ocurre después de `enforce_search_fallback(client_ip)` (línea 410-411,
   rate-limit sigue aplicando) y antes de construir la lista `tasks` de
   fan-out. Está envuelto en `if page == 1 and fanout_cache_key is not
   None:` — para páginas >1 el `cache.set` nunca se ejecuta, así que no hay
   posibilidad de efecto colateral en absoluto (ni interferencia ni
   escritura innecesaria). Correcto.

3. **Scoping de la clave de caché** — `_fanout_cache_key`
   (`backlogg/search/service.py:117-125`): `f"search_fanout:{item_type or
   'all'}:{q.strip().lower()}"`. Incluye `item_type` explícitamente (con
   sentinel `'all'` cuando es `None`), no solo el texto normalizado.
   Confirmado también por el test
   `test_search_fallback_page1_different_item_type_fires_separately`
   (`tests/test_search.py:384-421`), que siembra un resultado completo para
   `type=movie` y `type=series` por separado y verifica que ambas peticiones
   disparan el fan-out de forma independiente — si la clave no incluyera
   `item_type`, la segunda petición (`type=series`) habría sido suprimida
   por la marca dejada por la primera (`type=movie`).

4. **Los 4 tests nuevos prueban lo que dicen** (`tests/test_search.py`):
   - `test_search_fallback_page1_fires_first_time_even_when_local_page_full`
     (líneas 309-338) — página 1 completa (`limit=1`, 1 resultado local),
     confirma que el fan-out se dispara igualmente la primera vez.
   - `test_search_fallback_page1_not_refired_within_ttl_for_same_query`
     (líneas 341-366) — dos requests idénticas; usa `assert_called_once()`
     sobre los 4 mocks de `_ingest_*` y `refresh_mock`, lo cual exige
     exactamente 1 llamada total a través de ambas requests — es decir,
     prueba explícitamente que la segunda request NO invoca los mocks, no
     solo que el resultado observable es el mismo.
   - `test_search_fallback_page_gt1_still_fires_when_incomplete_after_page1_cached`
     (líneas 424-458) — página 1 (marca la caché) seguida de página 2
     incompleta; `assert ingest_movie_mock.call_count == 2` (y análogos para
     series/books/games/refresh) confirma que ambas dispararon el fan-out.
     Este es el test de regresión real que garantiza que la caché nunca
     suprime el disparo por página incompleta — confirmado experimentalmente
     en el punto 1 que falla con la lógica anterior.
   - `test_search_fallback_page1_different_item_type_fires_separately` — ver
     punto 3.
   Los 4 tests fallan de forma real contra el trigger anterior
   (`page_incomplete` únicamente), confirmando que no son tautológicos.

5. **Reutilización de `core/cache.py`** — `git diff main --stat --
   backlogg/core/cache.py` está vacío (archivo no tocado); confirmado por
   lectura completa del archivo, que ya define `Cache`/`InMemoryTTLCache`/
   `get_cache()` con el mismo patrón documentado que `core/rate_limit.py`
   (singleton de módulo, factory `get_cache()`, nunca se instancia la clase
   concreta directamente en los call sites). `backlogg/search/service.py`
   solo añade `from backlogg.core.cache import get_cache` y usa
   `cache.get(key)` / `cache.set(key, value, ttl_seconds)` — API pública
   documentada, sin acceder a `_store` ni a la implementación concreta.

6. **Aislamiento de tests** — el riesgo de contaminación cross-test del
   singleton `get_cache()` (misma preocupación planteada en el punto 6 del
   encargo) ya está cubierto por una fixture **preexistente y no tocada** en
   `tests/conftest.py:85-100`, `_reset_response_cache` (autouse, top-level,
   `cache.clear()` antes de cada test de todo el repo — no solo de este
   archivo). Confirmado con `git diff main -- tests/conftest.py` vacío y por
   mtime (archivo no modificado en ninguna de las 6 pasadas). Esto hace
   irrelevante que muchos tests de `tests/test_search.py` reutilicen el
   mismo texto `q=inception`: cada test arranca con la caché vacía, así que
   el orden de ejecución de pytest no puede afectar los resultados.

7. **`bash init.sh`** — verde: `991 passed` (988 + 3 netos: 4 tests nuevos
   menos 1 test renombrado/reemplazado — `test_search_fallback_not_fired_when_local_results_exist`,
   que probaba el comportamiento contrario ya obsoleto, fue eliminado — neto
   +3, coincide exactamente con lo reportado por el implementer), `ruff
   check`/`ruff format` OK. Ver output completo abajo. Verificado dos veces:
   antes y después del experimento de reversión temporal del punto 1 (mismo
   resultado, 991, confirmando que el archivo quedó restaurado sin diff
   residual).

8. **Alcance del diff** — confirmado por mtime (`stat` sobre todos los
   archivos con cambios en el árbol de trabajo, agrupados por bloque
   temporal 15:11–15:13, posterior a todas las pasadas anteriores) que esta
   sexta pasada tocó exactamente: `backlogg/search/service.py`,
   `backlogg/search/routes.py`, `docs/api.md`, `tests/test_search.py`,
   `progress/current.md`. Ningún otro archivo de `backlogg/`, `tests/` o
   `docs/` tiene mtime dentro de esa ventana. `git diff main --
   backlogg/core/cache.py backlogg/search/repository.py` (y el resto de
   adapters/services de books/games/movies/series) confirma cero cambios
   adicionales respecto a lo ya aprobado en pasadas previas.

## Docs

`docs/api.md` (párrafo inglés ~L62-73 y español "External fallback"
~L95-122) y los 2 sitios de `backlogg/search/routes.py` (`description=` del
endpoint y docstring de la función) describen consistentemente el nuevo
trigger de página 1 y el TTL de la caché, incluyendo el matiz de que una
página >1 ya completa (o página 1 ya comprobada) no consume cupo del
rate-limit, mientras que una página incompleta sí lo consume siempre.
Coincide con el código.

## Checkpoints (actualización)

- C5: [x] Todos los tests pasan de forma determinista y aislada (991),
  incluidos los 4 tests nuevos/modificados, verificados independientemente
  como regresión real (los 4 fallan con el trigger de la ronda anterior,
  pasan con el actual) y sin dependencia del orden de ejecución (caché
  limpiada por fixture autouse preexistente en `conftest.py`).
- C14: [x] Sin cambios en conversión de fechas.
- C20/C21/C22: [x] Sin cambios de capas — el cambio vive en `service.py`
  (orquestación) reutilizando `core/cache.get_cache()` ya existente, sin
  tocar `repository.py` ni introducir queries SQL nuevas en `service.py`.

## output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (63 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
283 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
991 passed in 27.57s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

## Observación no bloqueante

Igual que en las pasadas tercera, cuarta y quinta, `progress/impl_issue-14.md`
no se actualizó con una sección propia para este sexto cambio (fan-out
eager en página 1 + caché TTL); la documentación de este cambio vive solo en
`progress/current.md`. No afecta la corrección del código ni de los tests.

## Conclusión

El cambio implementa exactamente la decisión de producto descrita: la
página 1 de cualquier búsqueda con texto comprueba las APIs externas al
menos una vez por ventana TTL (10 min), deduplicado con la caché TTL
existente (`core/cache.get_cache()`, reutilizada sin modificar) y con
`item_type` incluido en la clave de caché. El trigger original de "página
incompleta" (crítico para el flujo de "cargar más" ya aprobado en rondas
anteriores) queda intacto y nunca es suprimido por la caché — verificado por
lectura del código (disyunción `or`) y experimentalmente (los 4 tests
nuevos fallan con el trigger anterior y pasan con el actual). La caché solo
se marca en página 1, sin efecto colateral en páginas posteriores. El
aislamiento de tests está garantizado por una fixture autouse preexistente
en `conftest.py` que limpia la caché antes de cada test del repo, sin
necesidad de tocarla en esta pasada. `bash init.sh` termina en verde (991
tests). El alcance del diff se limita a
`backlogg/search/service.py`, `backlogg/search/routes.py`, `docs/api.md`,
`tests/test_search.py` y `progress/current.md`, verificado por mtime y por
diff acumulado contra `main`. Se aprueba el cambio.
