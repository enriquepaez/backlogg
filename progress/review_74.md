# Review — feature 74: `credits_source_author_role`

**Veredicto:** APPROVED

Rama `feat/credits_source_author_role` (trabajo aún sin commitear: el diff
revisado es `git diff main` + `tests/test_credits_source_author_role.py`
sin trackear). `bash init.sh` en verde, ejecutado por el reviewer
(exit 0, 1431 tests). Ningún hallazgo bloqueante.

---

## Criterios de aceptación (12)

| # | Criterio | Estado | Evidencia |
|---|---|---|---|
| 1 | Rol `SOURCE_AUTHOR` en MOVIE y SERIES, documentado en `docs/schema.md` con la tabla de jobs | ✅ | `backlogg/shared/credits.py:53-62` (`TMDB_SOURCE_AUTHOR_JOBS`); `docs/schema.md:394-395, 422-436` ya lo documenta en `main` (`git diff main -- docs/` vacío) |
| 2 | Rol `WRITER` documentado como dato de ficha, no señal de recomendación | ✅ | `docs/schema.md:433`; `credits.py:64-72`; `AUTHORSHIP_ROLES` excluye `WRITER` a propósito (`credits.py:26-28`) |
| 3 | Allowlist por `job`, NUNCA por `department`, con test de regresión de storyboard | ✅ | Grep de `department` en `backlogg/`: solo comentarios (`movies/service.py:134`, `series/service.py:128`, `credits.py:32-34`), cero lógica. Test `test_storyboard_jobs_never_become_credits` (`Story Artist`/`Head of Story`/`Story Supervisor`/`Lyricist` → `[]` en movies **y** series) |
| 4 | `Story` y `Screenstory` excluidos de `SOURCE_AUTHOR`, con test | ✅ | Ninguno de los dos aparece en las tuplas de `credits.py:53-72`; `test_story_and_screenstory_are_not_source_author` fija que no producen **ni** `SOURCE_AUTHOR` ni `WRITER` |
| 5 | Poblado desde los credits ya solicitados — sin llamadas nuevas | ✅ | Verificado línea a línea: el diff no añade ni un `await` a un adapter ni un adapter nuevo. `map_movie_credits`/`map_series_credits` siguen siendo mapeo puro; `_fetch_series_credit_rows` y `_fetch_series_payload` siguen leyendo el mismo `detail["credits"]` que ya pedían con `append_to_response` |
| 6 | Allowlists como constante nombrada por dominio, no strings sueltos | ✅ | `MOVIE_CREW_JOB_ROLES` y `SERIES_CREW_JOB_ROLES` en `backlogg/shared/credits.py:68-73`; los servicios ya no llevan literales de job (antes `job != "Director"` en `movies/service.py`) |
| 7 | Consulta de repositorio: `person_id` → obras en TODOS los `item_type`, `{AUTHOR, SOURCE_AUTHOR}` como una sola clase | ✅ | `backlogg/recommendations/repository.py:270-332`; `union_all` sobre los 4 tipos de `_TYPE_CONFIG`; `Credit.role.in_(AUTHORSHIP_ROLES)` |
| 8 | El enlace exige credit `AUTHOR` sobre un libro **del catálogo** (filtro anti-traductor) | ✅ | `EXISTS` con `JOIN books ON books.id = credits.item_id` (`repository.py:298-307`). SQL compilado y revisado a mano: el `EXISTS` no se auto-correlaciona con el `union_all` (el FROM externo es la subconsulta anónima), así que es un filtro one-time correcto, no un cruce accidental |
| 9 | Issue #15 verificado resuelto para movies, series y books | ⛔ N/A | Fuera del alcance de esta implementación por decisión del leader: depende del borrado + siembra de producción, no ejecutado. **No bloquea esta review**; sigue pendiente antes de cerrar la feature |
| 10 | Tests: persona enlazada en ambos sentidos; adaptación real con guionista ≠ autor | ✅ | `test_authorship_links_a_person_works_in_both_directions` (BOOK+MOVIE+SERIES, `exclude` en ambos sentidos) y `test_real_adaptation_splits_writer_and_source_author_across_people` (*The Shining*: `SOURCE_AUTHOR={King}`, `WRITER={Kubrick, Johnson}`, conjuntos disjuntos, Kubrick además `DIRECTOR`) |
| 11 | `bruno/` sincronizado si cambia el contrato de `credits[]` | ✅ | El contrato no cambia: `CreditOut` sin tocar, `role` sigue siendo `str` libre, no hay endpoint nuevo/modificado/eliminado. Los dos `.bru` que tocan credits solo comprueban presencia de propiedades sobre `credits[0]`, y `credits[0]` sigue siendo el actor top-billed (`order_by billing_order asc nulls_last`, y el crew nuevo entra con `billing_order = NULL` igual que `DIRECTOR`). No procede tocar `bruno/` |
| 12 | `bash init.sh` en verde | ✅ | Ejecutado por el reviewer, exit 0. Salida completa abajo |

---

## Checkpoints (`CHECKPOINTS.md`)

- C1 `init.sh` exit 0: [x]
- C2 sin `print()` de debug: [x]
- C3 sin TODOs sin contexto: [x]
- C4 ruff check + format: [x]
- C5 tests verdes (1431): [x]
- C6 SQLAlchemy 2.0: [x] — `select()` 2.0 style, `Mapped`/`mapped_column` sin tocar
- C7 migración no recrea tablas: [x] N/A — no hay migración, y verificado que no hace falta: `Credit.role` es `String(50)` sin enum ni CHECK (`backlogg/shared/models.py`), los roles son texto libre
- C8 upgrade/downgrade: [x] N/A
- C9–C13 endpoints: [x] N/A — no hay rutas nuevas ni modificadas
- C14 fechas explícitas: [x] N/A — el crew de TMDB no aporta campos de fecha
- C15 external_ids únicos por test: [x] — `740001` / `740002` en los tests de backfill
- C16–C17 on-demand fallback: [x] — sin cambios de contrato; `test_on_demand_movie_persists_source_author_and_writer` y su gemelo de series comprueban que el fallback persiste antes de devolver
- C18 idempotencia del sync: [x] — la ruta bulk sigue deduplicando por `(item_type, item_id, person_id, role)` (`bulk_load.py:1026`) y la on-demand por `upsert_credit`
- C19 un error no aborta los demás jobs: [x] — sin cambios en el manejo de errores
- C20 sin lógica en `routes.py`: [x] — ningún `routes.py` tocado
- C21 sin queries en `service.py`: [x] — la consulta nueva vive en `recommendations/repository.py`; los servicios solo ganan mapeo puro
- C22 sin modelos ORM devueltos: [x] — `get_authorship_works` devuelve `Row`s de columnas escalares, mismo patrón que `get_seeds`/`get_popular_items`

---

## Verificaciones puntuales pedidas

**1. Allowlists literales contra `docs/schema.md`.** Comparadas una a una.
`SOURCE_AUTHOR`: `Novel, Book, Short Story, Comic Book, Graphic Novel,
Theatre Play, Original Story, Characters` — 8/8, ni una de más ni de menos.
`WRITER`: `Screenplay, Writer, Teleplay, Adaptation, Dialogue` — 5/5. Coinciden
con `docs/schema.md:432-433`. Correcto también que `SERIES_CREW_JOB_ROLES` no
lleve `Director`: `docs/schema.md:395` fija los roles de series en
`CREATOR, ACTOR, SOURCE_AUTHOR, WRITER`, y `CREATOR` sigue viniendo de
`created_by`. Hay test que lo fija (`test_series_crew_maps_source_author_and_writer_by_job`
mete un `job: "Director"` de serie y comprueba que no produce nada).

**2. Filtro por `department`.** Grep en `backlogg/`: cero. Las cuatro
apariciones son comentarios/docstrings que explican por qué NO se usa.

**3. `Story` / `Screenstory` / storyboard.** Fuera de ambas tuplas y fuera de
todo. Cubierto por dos tests distintos, más `Story` colado en el payload del
test de backfill (`test_targeted_backfill_writes_the_new_movie_roles`), que
verifica que tampoco cruza la ruta bulk.

**4. Cero llamadas HTTP nuevas.** Confirmado por lectura del diff completo: no
hay adapters nuevos importados, ni `await` nuevos, ni cambios en
`_TMDB_APPEND_TO_RESPONSE` (sigue siendo `"credits,external_ids"`). El `crew`
de series ya venía en el payload y simplemente se descartaba.

**5. Embudos únicos, verificados por grep de call sites (no de palabra).**
- Movies → `map_movie_credits`: `collect_movie_credits` (`movies/service.py:155`),
  que a su vez alimenta `_persist_movie_people` (on-demand: `movies/service.py`,
  `search/service.py:182`, `trending/service.py:68`) y `_fetch_movie_credit_rows`
  (backfill, `jobs.py:1022`); más `_fetch_movie_payload` (siembra, `jobs.py:444`).
- Series → `map_series_credits`: `collect_series_credits` (`series/service.py:147`)
  → `_persist_series_people` (on-demand: `series/service.py:192, 252, 346`,
  `search/service.py:251`, `trending/service.py:128`); más `_fetch_series_payload`
  (siembra, `jobs.py:459`) y `_fetch_series_credit_rows` (backfill, `jobs.py:1037`).
- Grep de `"DIRECTOR"|"ACTOR"|"CREATOR"|"AUTHOR"|"SOURCE_AUTHOR"|"WRITER"` en
  `backlogg/`: no queda ninguna otra ruta de escritura de credits de persona
  para MOVIE/SERIES fuera de estos dos mappers (`books` escribe `AUTHOR` por su
  cuenta, como debe).

**6. Rename `map_series_cast`.** Grep en todo el repo: cero referencias vivas.
Actualizados el import (`jobs.py:113`), los dos call sites (`jobs.py:459, 1037`),
el docstring cruzado de `movies/service.py:117`, los imports de
`tests/shared/test_slug_non_latin_fallback.py:42` y —lo importante— el
`patch("backlogg.scheduler.jobs.map_series_cast")` por string de
`tests/test_admin_sync.py:668`, que de no actualizarse habría reventado.
Solo quedan menciones históricas en `progress/`, que es correcto no tocar.

**7. Corrección del SQL de `get_authorship_works`.** Compilé la sentencia al
dialecto Postgres y la revisé. Es correcta:
- `union_all` de los 4 tipos, cada rama con `JOIN credits ON credits.item_id =
  <tabla>.id AND credits.item_type = '<TIPO>'` — el `item_type` va en el ON, no
  en un `WHERE` suelto, así que el modelo polimórfico no se cruza entre tablas.
- El `EXISTS` sale como filtro **no correlacionado** (`WHERE EXISTS (SELECT
  credits.id FROM credits JOIN books ON books.id = credits.item_id WHERE
  credits.person_id = :x AND item_type = 'BOOK' AND role = 'AUTHOR')`) aplicado
  sobre la subconsulta anónima. No hay auto-correlación indeseada con el
  `credits` de dentro del `union_all`, porque ese `credits` no está en el FROM
  externo. Postgres lo resuelve como InitPlan: se evalúa una vez.
- El `JOIN books` del gate es lo que hace el filtro **correcto** y no solo
  verde: sin él, un credit `AUTHOR` colgando de un `item_id` inexistente
  abriría la puerta (no hay FK en `credits`). Hay test específico
  (`test_author_credit_on_a_book_outside_the_catalog_does_not_open_the_gate`).
- `exclude` se aplica por rama y solo a la del `item_type` que corresponde:
  correcto, y probado en los dos sentidos.
- `limit` se aplica después del `order_by (item_type, item_id)`: determinista.

**8. Ubicación de la consulta.** Aceptable y bien argumentada. Es un
`repository.py` (frontera de persistencia intacta, C21), en el slice que la
consume de verdad (capa 0 de `docs/recommendations-plan.md`), que ya importa
los cuatro modelos de catálogo y ya construye lecturas cross-type con
`union_all` (`get_seeds`, `get_popular_items`). Las dos alternativas están bien
descartadas: en `books/repository.py` obligaría al slice de libros a consultar
movies y series, y en `shared/credits.py` metería `from backlogg.books.models
import Book` en una capa que hoy no importa ningún modelo de dominio. Sin
objeciones arquitectónicas.

**9. Deduplicación de `crew`.** `select_crew_credits` solo se aplica al `crew`;
el bucle de `cast` está literalmente igual (mismo `[:10]`, mismo
`character`/`order`). El orden de las filas se conserva (orden de payload, y
el crew sigue emitiéndose después del cast). La clave de dedup incluye el rol
(`(member["id"], role)`), así que una persona con `Novel` + `Screenplay` sigue
produciendo dos filas —cubierto por
`test_two_writing_jobs_for_one_person_yield_a_single_credit`, que además fija
que `Screenplay` + `Writer` colapsan en una. Verificado aguas abajo que
`bulk_load` construye los credits desde la lista completa (`credit_rows`,
`bulk_load.py:1006-1026`) y no desde la lista de personas deduplicada por slug
(`bulk_load.py:743`), así que multi-rol por persona no se pierde.

**10. Cambio fuera de alcance (`jobs.py`, comentario de
`_TMDB_APPEND_TO_RESPONSE`).** **Aceptable, se queda.** El comentario viejo
nombraba explícitamente la feature 74 y afirmaba que ella consumiría
`external_ids`; tras la reescritura de la feature eso es falso, así que dejarlo
habría sido dejar deuda de documentación creada por este mismo cambio. Verifiqué
además que la afirmación nueva es cierta: grep de `get("external_ids")` /
`["external_ids"]` en `backlogg/` no devuelve nada, `external_ids` sigue sin
consumidor. Son 3 líneas de comentario, sin efecto en el comportamiento.

**11. Calidad de los tests.** No son tautológicos:
- Los tests de mapper comparan **conjuntos completos** `{(nombre, rol)}`, no
  `assert x in y`, así que un job de más también rompería el test (no solo uno
  de menos). Los 13 jobs de las dos allowlists están enumerados uno a uno.
- Los negativos usan `== []`, que es la aserción fuerte correcta.
- Los tests de ruta de escritura y los de la consulta cross-type corren contra
  **Postgres real** (fixture `db` de `tests/conftest.py`, `TEST_DATABASE_URL`
  con migraciones aplicadas y guardia anti-producción), no contra SQLite ni
  mocks; solo se mockean las llamadas externas. Los del backfill van
  end-to-end por `sync_missing_credits` → `bulk_load_credits` y comprueban
  tanto las filas persistidas como `credits_written == 4`.
- El test de adaptación real fija lo que de verdad importa de la feature:
  `SOURCE_AUTHOR` y `WRITER` sobre personas distintas y conjuntos disjuntos.

---

## Hallazgos

### Bloqueantes

Ninguno.

### Menores (no bloquean; a decidir por el leader)

1. **Comentario obsoleto en el frontend** —
   `apps/web/src/app/[locale]/[type]/[slug]/page.tsx:86` sigue diciendo que el
   crew de TMDB se filtra por `job == "Director"`, cosa que este cambio deja
   sin ser cierta. **El comportamiento no se rompe** (`peopleByRole` filtra por
   `credit.role === "DIRECTOR"`, y los roles nuevos simplemente se ignoran), y
   el shape de la respuesta no cambia, así que no hace falta regenerar
   `packages/api-client` ni pasar el gate de `pnpm typecheck`. Es solo un
   comentario desactualizado, fuera del alcance backend de esta feature.
2. **Hueco de cobertura simétrico en la siembra de series** — hay test del
   embudo de siembra de movies (`test_seeding_payload_carries_the_writing_crew`
   sobre `_fetch_movie_payload`) pero no el equivalente sobre
   `_fetch_series_payload`. La ruta está cubierta indirectamente (mismo mapper,
   verificado por grep; y `test_admin_sync.py:668` la ejercita con el mapper
   parcheado), pero un test simétrico sería más barato que el razonamiento.
3. **`get_authorship_works` puede devolver dos filas del mismo ítem** si una
   persona tiene `AUTHOR` **y** `SOURCE_AUTHOR` sobre el mismo `(item_type,
   item_id)` — legítimo por `uq_credit`, poco probable, pero el consumidor
   (feature 82) tendrá que deduplicar por ítem o quedarse con un rol. Conviene
   anotarlo en el plan de la 82.
4. **`limit` sin test.** El parámetro existe y está bien colocado (después del
   `order_by`), pero ningún test lo ejercita.
5. **Criterio de aceptación 9 sigue abierto** (issue #15: cobertura de credits
   en movies, series y books). Explícitamente fuera del alcance de esta
   implementación, pero la feature **no debería marcarse `done`** sin ejecutar
   el borrado + siembra de producción y volver a medir. Además, como señala el
   implementer, los ítems ya sellados con `credits_synced_at` no reaparecen
   como huecos: en la QA manual de dev hará falta `--recheck` para ver
   `SOURCE_AUTHOR`/`WRITER` sobre ítems ya visitados.
6. **Imprecisiones en `docs/recommendations-plan.md`** (detectadas por el
   implementer y confirmadas): promete una migración Alembic que no hace falta,
   y su tabla sigue diciendo `Games → falta DIRECTOR`, contradiciendo la
   decisión del 2026-09-04 ya reflejada en `docs/schema.md`. Es deuda de docs,
   no de código; corresponde a una rama `docs/`.

---

## Nota sobre el estado del árbol

El trabajo está **sin commitear** (`git diff main --stat` vacío contra
`main...HEAD`; todo vive en el working tree, y
`tests/test_credits_source_author_role.py` está sin trackear). El commit tendrá
que incluir explícitamente el archivo nuevo. `backend_feature_list.json` pasa
`pending` → `in_progress` para la 74; correcto, el implementer no la ha marcado
`done`.

---

## Output de `bash init.sh` (ejecutado por el reviewer, exit code 0)

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
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
All checks passed!
[OK]    ruff check pasa
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
309 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
........................................................................ [  5%]
........................................................................ [ 10%]
........................................................................ [ 15%]
........................................................................ [ 20%]
........................................................................ [ 25%]
........................................................................ [ 30%]
........................................................................ [ 35%]
........................................................................ [ 40%]
........................................................................ [ 45%]
........................................................................ [ 50%]
........................................................................ [ 55%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 70%]
........................................................................ [ 75%]
........................................................................ [ 80%]
........................................................................ [ 85%]
........................................................................ [ 90%]
........................................................................ [ 95%]
...............................................................          [100%]
1431 passed in 39.36s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
