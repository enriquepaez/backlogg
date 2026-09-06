# Informe de implementación — feature 74 `credits_source_author_role`

- **Rama**: `feat/credits_source_author_role`
- **Fecha**: 2026-09-06
- **Estado**: implementado, pendiente de review
- **Migración Alembic**: **ninguna, y no hace falta** (verificado, ver §5)

---

## 1. Archivos tocados

| Archivo | Qué cambia |
|---|---|
| `backlogg/shared/credits.py` | **Allowlists por dominio** (`TMDB_SOURCE_AUTHOR_JOBS`, `TMDB_WRITER_JOBS`, `MOVIE_CREW_JOB_ROLES`, `SERIES_CREW_JOB_ROLES`), la clase de autoría `AUTHORSHIP_ROLES` y el helper `select_crew_credits()` |
| `backlogg/movies/service.py` | `map_movie_credits()`: el bucle de `crew` pasa de `job == "Director"` a la allowlist `MOVIE_CREW_JOB_ROLES`. Docstring actualizado (referencia al nombre nuevo del mapper de series) |
| `backlogg/series/service.py` | `map_series_cast()` → **`map_series_credits()`**, que ahora sí lee `crew` con `SERIES_CREW_JOB_ROLES`. Docstrings de `map_series_credits` y `collect_series_credits` actualizados |
| `backlogg/scheduler/jobs.py` | Import y 2 call sites del rename (`_fetch_series_payload`, `_fetch_series_credit_rows`). Corrección de un comentario obsoleto sobre `external_ids` (ver §6, hallazgo 2) |
| `backlogg/recommendations/repository.py` | Nueva consulta cross-type `get_authorship_works()` |
| `tests/test_credits_source_author_role.py` | **Nuevo** — 17 tests de la feature |
| `tests/shared/test_slug_non_latin_fallback.py`, `tests/test_admin_sync.py` | Solo el rename `map_series_cast` → `map_series_credits` (incluido el `patch(...)` por string en `test_admin_sync.py:668`, que si no se actualiza revienta) |
| `backend_feature_list.json` | La feature 74 ya venía en `in_progress` (no la he marcado `done`) |

Sin cambios en `bruno/`, `packages/api-client`, `apps/web`, `alembic/` ni docs.

---

## 2. Allowlists (criterio: «constante nombrada por dominio, no strings sueltos»)

Todo vive en `backlogg/shared/credits.py`, que ya era el módulo compartido de
credits (ahí estaba `get_credits_for_item`) y no importa ningún dominio, así
que movies, series y recommendations pueden depender de él sin ciclos:

- `TMDB_SOURCE_AUTHOR_JOBS` — `Novel`, `Book`, `Short Story`, `Comic Book`,
  `Graphic Novel`, `Theatre Play`, `Original Story`, `Characters`. Literal de
  `docs/schema.md`; ni ampliada ni recortada.
- `TMDB_WRITER_JOBS` — `Screenplay`, `Writer`, `Teleplay`, `Adaptation`,
  `Dialogue`.
- `MOVIE_CREW_JOB_ROLES` = `{"Director": "DIRECTOR"}` + las dos listas
  anteriores mapeadas a su rol.
- `SERIES_CREW_JOB_ROLES` = solo las dos listas de escritura. **No** lleva
  `Director`: `docs/schema.md` fija los roles de series en
  `CREATOR, ACTOR, SOURCE_AUTHOR, WRITER`, y `CREATOR` sigue saliendo de
  `created_by` del detalle, no del `crew`. Hay test que fija que un `crew` de
  serie con `job: "Director"` no produce nada.
- `Story`, `Screenstory`, `Story Artist`, `Head of Story`, `Story Supervisor`,
  `Lyricist` no están en ninguna lista → no se persisten. En ningún punto se
  lee `department`.

`select_crew_credits(crew, job_roles)` devuelve `(member, role)` en orden de
payload y **deduplica por `(id de persona, rol)`**. Esto no es cosmético: TMDB
acredita rutinariamente a la misma persona con `Screenplay` **y** `Writer`, que
colapsan en el mismo rol `WRITER`; sin deduplicar, el mismo tuple de
`uq_credit` se emitía dos veces. La ruta bulk lo habría absorbido (ya dedupe en
`_load_people_credits`) y la on-demand también (`upsert_credit`), pero emitir la
fila duplicada es escritura redundante y ruido en `credits_written`. Se
deduplica solo el `crew`; el `cast` queda exactamente como estaba.

---

## 3. Dónde puse la consulta cross-type y por qué

**`backlogg/recommendations/repository.py::get_authorship_works()`**.

Justificación (descarté dos alternativas):

- **No en `books/repository.py`** — la consulta devuelve MOVIE y SERIES además
  de BOOK; meterla en el slice de libros haría que el dominio books
  importase/consultase movies y series, que es justo lo que la regla de
  vertical slices evita.
- **No en `shared/credits.py`** — el filtro anti-traductor exige *join contra
  la tabla `books`* («un libro **del catálogo**»), y hoy **ningún módulo de
  `backlogg/shared/` importa un modelo de dominio** (solo `core.database` y
  `shared.*`). Meter `from backlogg.books.models import Book` ahí invertiría la
  dirección de dependencia de toda la capa shared.
- **Sí en `recommendations/repository.py`** — es el consumidor real (capa 0 de
  `docs/recommendations-plan.md`), es un `repository.py` (frontera de
  persistencia respetada), ya importa los cuatro modelos de catálogo y ya
  construye lecturas cross-type con `union_all` (`get_seeds`,
  `get_popular_items`). La consulta encaja en el patrón existente sin inventar
  capa nueva.

Firma y comportamiento:

```
get_authorship_works(db, person_id, *, exclude=None, limit=None) -> list[Row]
# filas: item_type, item_id, title, slug, role
```

- `union_all` sobre **todos** los `item_type` de `_TYPE_CONFIG` (MOVIE, SERIES,
  BOOK, GAME) uniendo `credits` con la tabla del ítem; GAME está por
  completitud polimórfica y aporta cero filas por construcción (games no tienen
  credits de persona, decisión del 2026-09-04) — no implementa nada de games.
- `{AUTHOR, SOURCE_AUTHOR}` se tratan como una sola clase vía la constante
  `AUTHORSHIP_ROLES`. `WRITER` **no** entra: peso cero, es dato de ficha.
- **Filtro anti-traductor**: toda la sentencia está condicionada a un `EXISTS`
  de «credit `AUTHOR` sobre `item_type = BOOK` **que exista en `books`**». Se
  evalúa una vez, en el mismo round-trip. El join con `books` es deliberado:
  `credits` no tiene FK real (`docs/conventions.md`), así que la fila sola no
  demuestra que el libro esté en el catálogo.
- `exclude=(item_type, item_id)` quita la obra de partida, que es lo que
  permite probar el enlace «en ambos sentidos» (libro→pantalla y
  pantalla→libro) con la misma función.

No hay ruta HTTP nueva: la consulta la consumirá el ranker en la feature 82.
Por eso tampoco hay `.bru` nuevo (ver §4).

---

## 4. Bruno / api-client / frontend

**El shape de `credits[]` no cambia.** `CreditOut`
(`backlogg/shared/schemas.py`) es el mismo, `get_credits_for_item` no filtra
por rol y `role` es un `str` libre tanto en el schema Pydantic como en
`packages/api-client/src/schema.d.ts` (`role: string`, sin enum ni literal
union). Lo único que cambia es que aparecen **filas nuevas** con roles nuevos
dentro del array que ya existía. Los dos `.bru` que tocan credits
(`bruno/Movies/Get movie by slug.bru`, `bruno/Series/Get series by slug.bru`)
comprueban `person_name` / `person_slug` / `role` / `billing_order` sobre
`credits[0]` y siguen siendo válidos.

Por tanto: **`bruno/` no se toca** (no hay endpoints nuevos, modificados ni
eliminados) y **no hace falta regenerar `packages/api-client`** ni tocar
`apps/web`. No he encontrado ningún consumidor de backend que filtre credits
por rol.

---

## 5. Verificaciones que hice yo (no asumidas)

1. **Sin migración**: `Credit.role` es `mapped_column(String(50))` en
   `backlogg/shared/models.py:51`; en `alembic/versions/0001_shared_models.py`
   la tabla solo declara `uq_credit` y los índices
   (`idx_credits_person/item/role`). No hay enum PostgreSQL ni CHECK sobre
   `role` en ninguna de las migraciones que mencionan `credits` (0001, 0005,
   0034). Roles nuevos = texto nuevo, nada que migrar.
2. **Movies: embudo único** — `map_movie_credits` lo usan `collect_movie_credits`
   (on-demand + backfill vía `_fetch_movie_credit_rows`) y `_fetch_movie_payload`
   (siembra, `jobs.py:443`). Un solo cambio cubre las tres rutas.
3. **Series: los tres call sites del rename** actualizados
   (`series/service.py:131`, `jobs.py:458`, `jobs.py:1036`) más el import de
   `jobs.py:113`, el docstring de `movies/service.py` que citaba
   `map_series_cast` y los tests que lo importaban o lo parcheaban por string.
   `grep map_series_cast` en `backlogg/` y `tests/` ya no devuelve nada
   (queda la mención histórica en `progress/impl_issue-18.md`, que no toco).
4. **Cero llamadas HTTP nuevas**: no se añade ningún `await` a un adapter. El
   `crew` de series ya venía en el payload de `/tv/{id}/credits` y en el
   `append_to_response=credits` del detalle; simplemente se ignoraba.

---

## 6. Hallazgos para el reviewer

1. **Discrepancia doc↔realidad (no la he corregido, como se me indicó)**:
   `docs/recommendations-plan.md` (capa 0) dice que el puente se resuelve «con
   una migración Alembic y un cambio en el adaptador de ingesta». La migración
   no existe ni hace falta — `credits.role` es texto libre. La misma tabla de
   esa sección sigue listando `Games → falta DIRECTOR`, que contradice la
   decisión del 2026-09-04 ya reflejada en `docs/schema.md` («games have no
   person credits — by decision»). Ambas son imprecisiones de
   `recommendations-plan.md`, no del código; las dejo señaladas para que el
   leader decida si las corrige en una rama de docs.
2. **Comentario de código obsoleto corregido** (`backlogg/scheduler/jobs.py`,
   sobre `_TMDB_APPEND_TO_RESPONSE`): decía «`external_ids` no se lee aún —
   feature 74 (SOURCE_AUTHOR) es quien lo consume». Falso tras la reescritura
   de la feature: `SOURCE_AUTHOR` sale de `credits.crew`, no de `external_ids`.
   Reescribí el comentario para que diga la verdad (que `external_ids` sigue
   sin consumidor y viaja gratis). Es el único cambio del repo que no es
   estrictamente necesario para la feature; si el reviewer lo considera fuera
   de alcance, se revierte en dos líneas.
3. **Riesgo abierto que ya anotó el leader**: el criterio «issue #15 verificado
   como resuelto para movies, series y books» depende del borrado + siembra de
   producción, que no se ha ejecutado. No entra en esta implementación.
4. **Cobertura real de los roles nuevos**: solo se poblarán al re-sincronizar
   credits. Los ítems ya sellados con `credits_synced_at` **no** vuelven a la
   lista de huecos, así que en la DB de dev habrá que pasar el backfill con
   `--recheck` para ver `SOURCE_AUTHOR`/`WRITER` en items ya visitados. Es
   comportamiento existente de la feature 85, no una regresión, pero conviene
   saberlo en la QA manual.

---

## 7. Tests añadidos (`tests/test_credits_source_author_role.py`, 17)

**Mappers (puros, sin DB ni red)**

| Test | Cubre |
|---|---|
| `test_movie_crew_maps_source_author_and_writer_by_job` | Los 13 jobs de las dos allowlists caen en su rol + `DIRECTOR` sigue funcionando |
| `test_series_crew_maps_source_author_and_writer_by_job` | Series leen `crew`; un `job: "Director"` de serie **no** produce credit |
| `test_storyboard_jobs_never_become_credits` | **Regresión pedida**: `Story Artist` / `Head of Story` / `Story Supervisor` (+ `Lyricist`) no producen ningún credit, ni en movies ni en series |
| `test_story_and_screenstory_are_not_source_author` | `Story` y `Screenstory` no producen `SOURCE_AUTHOR` **ni** `WRITER` (lista vacía) |
| `test_real_adaptation_splits_writer_and_source_author_across_people` | **Adaptación real** (*The Shining*): `SOURCE_AUTHOR` = {King}, `WRITER` = {Kubrick, Johnson}, conjuntos disjuntos, y Kubrick además `DIRECTOR` |
| `test_two_writing_jobs_for_one_person_yield_a_single_credit` | `Screenplay`+`Writer` de la misma persona → un solo `WRITER` (no duplica `uq_credit`) |
| `test_empty_or_missing_crew_is_harmless` | Payload `None` / sin `crew` |

**Ruta de escritura 1 — on-demand**

| Test | Cubre |
|---|---|
| `test_on_demand_movie_persists_source_author_and_writer` | `get_movie` fallback: roles nuevos en `credits` de la DB, storyboard descartado, y la respuesta del endpoint los devuelve sin cambio de shape |
| `test_on_demand_series_persists_source_author_and_writer` | `get_series` fallback: `ACTOR` + `CREATOR` (de `created_by`) + `SOURCE_AUTHOR` + `WRITER`, storyboard descartado |

**Ruta de escritura 2 — siembra / backfill**

| Test | Cubre |
|---|---|
| `test_seeding_payload_carries_the_writing_crew` | `_fetch_movie_payload` (embudo de la **siembra**, `append_to_response=credits`) |
| `test_targeted_backfill_writes_the_new_movie_roles` | `sync_missing_credits("movie")` end-to-end contra Postgres, vía `bulk_load_credits`; `Story Artist` y `Story` fuera; `credits_written == 4` |
| `test_targeted_backfill_writes_the_new_series_roles` | Igual para series (`Comic Book` → `SOURCE_AUTHOR`, `Dialogue` → `WRITER`, `Head of Story` fuera) |

**Consulta cross-type (Postgres real)**

| Test | Cubre |
|---|---|
| `test_authorship_links_a_person_works_in_both_directions` | Persona con obra en **tres** `item_type`; enlazada libro→película/serie y película→libro con `exclude` |
| `test_translator_credited_as_book_is_not_linked` | **El traductor**: `SOURCE_AUTHOR` sin `AUTHOR` de libro → sin enlace |
| `test_author_credit_on_a_book_outside_the_catalog_does_not_open_the_gate` | Credit `AUTHOR` colgando de un `item_id` inexistente (no hay FK) → sin enlace |
| `test_writer_and_other_roles_are_not_authorship` | `WRITER`/`DIRECTOR` no son autoría |
| `test_authorship_query_ignores_other_peoples_credits` | Persona sin credits de autoría → lista vacía |

Además, los tests preexistentes de `map_series_cast` siguen pasando bajo el
nombre nuevo.

---

## 8. `bash init.sh` — salida literal

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
[OK]    backend_feature_list.json válido (87 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
309 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
1431 passed in 34.63s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(exit code `0`. Baseline antes de tocar nada: 1414 tests; ahora 1431 = +17.)

---

## Adenda — `Original Story` fuera de la allowlist (QA manual)

Decisión del usuario durante la QA manual contra la API real: `Original Story`
sale de `TMDB_SOURCE_AUTHOR_JOBS`. Evidencia medida:

```
GET /v1/movies/inside-out-2015
   SOURCE_AUTHOR  Pete Docter
   SOURCE_AUTHOR  Ronnie del Carmen
```

*Inside Out* no adapta ninguna obra previa: esos dos credits salen del job
`Original Story`, que en TMDB significa lo mismo que `Story` y `Screenstory`
—argumento escrito para la pantalla, material original, no obra previa— y esos
dos ya estaban excluidos deliberadamente. El error estaba en la especificación
de la feature, no en la implementación. El filtro anti-traductor ya impedía que
esto generara enlaces cross-type falsos (ambas personas devuelven 0 obras en
`get_authorship_works`), pero la etiqueta de rol en la ficha era incorrecta y
está a punto de hornearse en un catálogo de 118.850 ítems.

### Archivos modificados

- `backlogg/shared/credits.py` — `Original Story` fuera de
  `TMDB_SOURCE_AUTHOR_JOBS`; la lista queda en 7 jobs (`Novel`, `Book`,
  `Short Story`, `Comic Book`, `Graphic Novel`, `Theatre Play`, `Characters`).
  El comentario que ya documentaba la exclusión de `Story`/`Screenstory` ahora
  nombra también `Original Story`, con el caso *Inside Out* como referencia.
  `Characters` **no** se toca: Bob Kane → Batman y Conan Doyle → Sherlock son
  puentes legítimos y se verificaron en la QA. `TMDB_WRITER_JOBS` intacta.
- `tests/test_credits_source_author_role.py` — ver abajo.
- `docs/schema.md` — en la tabla de la sección «`SOURCE_AUTHOR` vs `WRITER`
  (movies and series)», `Original Story` sale de la celda de jobs de
  `SOURCE_AUTHOR`; la frase que explicaba la exclusión de `Story` y
  `Screenstory` ahora cubre los tres, con el motivo (material original escrito
  para la pantalla, no obra previa) y el ejemplo de *Inside Out*.

Fuera de alcance por reparto explícito: `docs/recommendations-plan.md` y
`backend_feature_list.json` los actualiza el leader.

### Tests cambiados y por qué

- `test_movie_crew_maps_source_author_and_writer_by_job` — enumera la allowlist
  completa y compara conjuntos, así que fallaba por construcción. Se elimina el
  miembro de crew con job `Original Story` y su par esperado
  `("Original Storyteller", "SOURCE_AUTHOR")`. Sigue siendo la prueba de que la
  allowlist es exactamente la que documenta `docs/schema.md`.
- `test_story_and_screenstory_are_not_source_author` → renombrado
  `test_story_screenstory_and_original_story_are_not_source_author`. Se extiende
  el test que ya fijaba la exclusión en vez de añadir uno nuevo: es el sitio
  natural, los tres jobs se excluyen por el mismo motivo y separarlos sugeriría
  que hay dos reglas distintas. Lleva un comentario que deja escrito ese motivo
  común y el caso *Inside Out* que lo detectó. Cubre mappers de movies y series.
- Docstring del módulo actualizado para que la lista de exclusiones que anuncia
  coincida con la que prueba.

No se añaden ni se quitan tests: siguen siendo 1431.

### `bash init.sh`

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
[OK]    backend_feature_list.json válido (87 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
309 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
1431 passed in 44.90s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(exit code `0`, en verde.)
