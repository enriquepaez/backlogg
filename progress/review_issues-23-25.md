# Review — issues #23 y #25 (rama `fix/external_id_identity_resolution`)

**Veredicto:** APPROVED

**Revisor:** agente reviewer · **Fecha:** 2026-09-06
**Alcance revisado:** `git diff main` (13 archivos de `backlogg/`, 1 de `scripts/`,
4 de `docs/`, 4 de `tests/`) + los dos sin trackear
(`backlogg/shared/identity.py`, `tests/shared/test_external_id_identity.py`).
**Informe del implementer:** `progress/impl_issues-23-25.md` — verificado contra
el codigo, no aceptado de palabra. Ver §7 (discrepancias).

---

## 1. Checkpoints (`CHECKPOINTS.md`)

| # | Estado | Nota |
|---|---|---|
| C1 `bash init.sh` sale 0 | [x] | Ejecutado por mi 3 veces verdes (ver §6 y §8) |
| C2 sin `print()` de debug | [x] | `identity.py` y los tests nuevos usan `logging` |
| C3 sin TODOs sin contexto | [x] | grep de TODO/FIXME/XXX en los archivos nuevos: 0 |
| C4 `ruff check` + `format` | [x] | `All checks passed!` / `311 files already formatted` |
| C5 todos los tests pasan | [x] | 1448 passed |
| C6 SQLAlchemy 2.0 | [x] | `select()` / `update()` / `AsyncSession`; ni `db.query()` ni `Session` sincrona |
| C7 migracion no recrea tablas | n/a | No hay migracion. Verificado: el diff no toca `alembic/`, y `identity.py` solo hace SELECT + `UPDATE ... SET slug` |
| C8 `upgrade()`/`downgrade()` | n/a | idem |
| C9 handlers `async` + `Depends` | n/a | Ningun `routes.py` en el diff |
| C10 `response_model` Pydantic v2 | n/a | Sin endpoints nuevos ni contratos cambiados |
| C11 URLs con slugs | [x] | Sin cambios de URL |
| C12 404 si no existe | [x] | `movies/service.get_movie` intacto salvo el kwarg |
| C13 test de happy path por endpoint | n/a | Sin endpoints nuevos |
| C14 fechas convertidas explicitamente | [x] | No se anade parseo de fechas; los payloads de test usan `date(...)`/`datetime` reales |
| C15 external_ids unicos por test | [x] | Rangos nuevos `9310xx`/`9320xx`/`OL931004W` y `2_000_000_0xx` para huerfanos; grep sin colisiones con tests preexistentes |
| C16 fallback persiste antes de devolver | [x] | Sin cambios en el orden; `upsert_*` sigue persistiendo antes del return |
| C17 404 si la API externa tampoco lo tiene | [x] | Sin cambios |
| C18 sync idempotente | [x] | **Mejora directa**: es lo que arregla el #23. `test_the_batch_route_follows_the_external_id_when_the_title_changes` y `test_the_tmdb_284753_regression` lo fijan |
| C19 un job no aborta los demas | [x] | `_write_items_individually` conserva su `try/except` + `rollback_quietly` |
| C20 sin logica en `routes.py` | [x] | Sin cambios en routes |
| C21 sin queries en `service.py` | [x] | Los call sites de service solo anaden un kwarg. Ningun `select()` nuevo en services. Verificado por diff |
| C22 sin ORM crudo en respuestas | [x] | Sin cambios de serializacion |

**Ninguno en `[ ]`.**

Bruno: correcto que no se toque. `git diff main --stat` no contiene ningun
`routes.py` ni schema de respuesta; no hay endpoint creado, modificado ni
eliminado, asi que no hay `.bru` que sincronizar ni huerfano que borrar.

---

## 2. Los puntos que el leader pidio con lupa

### 2.1 Tests preexistentes modificados

Es el riesgo principal de la rama y lo he auditado uno a uno, contrastando lo
que **afirmaba** cada asercion antigua con lo que el codigo hace ahora. Detalle
completo en §3. Resumen: **6 tests tocados, los 6 legitimos, ninguno aflojado.**

### 2.2 Cobertura de rutas de escritura — comprobado por grep, no de palabra

`grep -rn --include="*.py" -e upsert_movie -e upsert_series -e upsert_book -e upsert_game backlogg scripts`
da 13 call sites fuera de las definiciones. Clasificados:

| Call site | Pasa `external_id` |
|---|---|
| `movies/service.py:234` (`get_movie`) | si |
| `movies/service.py:318` (`get_similar_movies`) | si |
| `series/service.py:246` (`get_series`) | si |
| `series/service.py:339` (`get_similar_series`) | si |
| `books/service.py:207` (`get_book`) | si |
| `games/service.py:86` (`get_game`) | si |
| `games/service.py:166` (`get_similar_games`) | si |
| `search/service.py:176` (movies fan-out) | si |
| `search/service.py:247` (series fan-out) | si |
| `search/service.py:331` (books fan-out) | si |
| `search/service.py:373` (games fan-out) | si |
| `trending/service.py:61` y `:121` | si |
| `scripts/bench_bulk_load.py:189` | si |
| `{movies,series,books,games}/repository.py::_bulk_fallback_upsert` | **no lo necesita** — es el `spec.upsert_item` del loader, y la identidad se resuelve un nivel mas arriba, en `jobs._write_items_individually` (comprobado en `jobs.py:281-288`) |

`grep -rn -e bulk_load_items -e upsert_item` confirma que solo hay **dos**
puntos de entrada de escritura de catalogo: `bulk_load_items` (alineado en
`bulk_load.py:843`) y `_write_items_individually` (alineado en `jobs.py:281`).
Los cuatro `BulkItem(...)` construidos en `jobs.py` (linea 675 movies/series,
875 books, 969 games) llevan `external_id`, asi que los cuatro tipos entran por
la puerta con identidad tanto en bulk como on-demand.

**No queda ninguna ruta de escritura de catalogo sin resolver identidad.** Las
dos exclusiones del informe se sostienen: `sync_missing_credits` no escribe
items (solo `credits`), y `admin_update_*` no viene de una fuente externa —
verificado ademas que **nunca reescribe el slug** (`admin/service.py:234` pasa
`slug=item.slug`), asi que no puede desalinear la identidad.

### 2.3 Colision de slug al realinear — tratada, no revienta, y esta probada

Tres ramas en `identity.py`, cada una con su test y su log distinguible:

- **slug ocupado por otra fila** (`identity.py:176-188`) → conserva el slug,
  redirige la escritura, `logger.warning` con el `item_id` del ocupante.
  Test: `test_a_rename_into_a_slug_another_item_owns_keeps_the_old_slug`.
- **slug disputado dentro del lote** (`identity.py:189-200`) → nadie renombra.
  Test: `test_two_items_of_one_batch_renaming_into_the_same_slug_keep_theirs`.
- **`title` bloqueado por admin** (`identity.py:152-163`).
  Test: `test_an_admin_locked_title_is_not_renamed_but_still_finds_its_row`.

Y la carrera que la comprobacion no puede cubrir: el `UPDATE` va en
`session.begin_nested()` y el `except IntegrityError` devuelve los slugs
actuales, de modo que el upsert posterior sigue cayendo en la fila correcta.
Test: `test_losing_the_race_for_a_slug_is_absorbed_by_the_savepoint`.

Revisado ademas el caso que ningun test nombra, el **intercambio de slugs**
(A quiere el de B y B el de A): `owners` devuelve `{b: id_A, a: id_B}`, los dos
caen en la rama "el slug ya es de otra fila" y ninguno renombra. No hay
`IntegrityError` posible por esa via. Correcto por construccion.

La decision (conservar el slug guardado, URL obsoleta, cero duplicados) es
defendible y esta argumentada frente a las tres alternativas descartadas.

### 2.4 El `LEFT JOIN` del #25 — SQL compilado revisado

Compilado contra el dialecto de Postgres:

```sql
SELECT seed_targets....
FROM seed_targets
LEFT OUTER JOIN external_ids
  ON external_ids.item_type = seed_targets.item_type
 AND external_ids.source = seed_targets.source
 AND external_ids.external_id = seed_targets.external_id
LEFT OUTER JOIN movies ON movies.id = external_ids.item_id
WHERE seed_targets.item_type = :item_type_1
  AND seed_targets.source = :source_1
  AND movies.id IS NULL
```

Correcto. Los dos joins son `LEFT`, asi que un NULL del primero solo puede
producir NULL en el segundo y `movies.id IS NULL` cubre de una vez "no hay
enlace" y "hay enlace que no llega a nada" — el razonamiento del docstring es
exacto. **No excluye targets legitimamente convergidos**: un target enlazado a
una fila viva produce `movies.id NOT NULL` y sale de la lista.

No multiplica filas: `uq_external_id` es UNIQUE sobre
`(item_type, source, external_id)` desde la migracion 0036, asi que el primer
join da como mucho una fila y `count_seed_target_progress` (que reusa el mismo
stmt con `with_only_columns`) no puede contar de mas.

**Las dos direcciones estan probadas**, que era la exigencia:

- target con enlace al vacio **sigue en la lista**:
  `test_a_target_whose_triple_points_at_no_item_stays_workable` (y ademas
  comprueba que acumula `attempts` hasta `unlinkable`/`stuck`, o sea que la
  reapertura no degenera en reintento eterno);
- target propio **sale de la lista**: `test_a_target_linked_to_its_own_item_is_done`
  y `test_a_renamed_seeded_target_stays_converged`.

`ValueError` para `item_type` sin modelo: hoy `SEED_TARGET_SOURCES` solo tiene
MOVIE y SERIES, ambos en `_ITEM_MODELS`, asi que es inalcanzable en produccion —
es una guarda, no una regresion.

### 2.5 `skipped_links` (#22) no se rompe

El contador sigue midiendo lo mismo (`item_id` distinto = perdida, igual =
idempotencia). Lo verifique en `bulk_load.py:668-673` y en
`shared/external_ids.py`: sin cambios.

Lo importante para el leader: **la cobertura del caso "otra fila viva reclama la
terna" no se ha perdido**, porque el test que lo cubre en la ruta per-item
—`test_a_link_claimed_by_another_item_is_counted`, linea 159— **no esta
tocado** y sigue verde, igual que
`test_two_items_of_one_batch_fighting_over_a_triple_are_counted` y
`test_a_skipped_link_is_logged_with_both_item_ids`. Los dos escenarios que si
cambiaron de renombrado a enlace huerfano cubren la ruta de lote, y el huerfano
es una perdida real y permanente: el join de identidad es INNER
(`identity.py:135`), asi que un enlace muerto no resuelve nada y la fila nueva
se escribe sin enlace. Cubierto ademas a nivel de funcion por
`test_a_link_pointing_at_no_item_decides_no_identity`, que asserta
`resolved == {}`.

Ninguna asercion del contador se ha relajado: en los tres tests reescritos
siguen siendo `skips.count == 1`, mismo `attempted_item_id`, mismo
`claimed_by_item_id` (ahora el id huerfano).

### 2.6 Coste en round trips — por lote, no por item

Leido en el codigo, no en el informe:

- `_align_batch_slugs` (`bulk_load.py:783-813`) construye **un** dict `proposed`
  con todo el lote y hace **una** llamada a `align_slugs_to_external_ids`, que
  emite **un** `SELECT ... WHERE external_id IN (...)`. No hay bucle con `await`
  dentro.
- `_slug_owners` es **un** `SELECT ... WHERE slug IN (...)`, y solo se emite si
  hay renombrados.
- El `UPDATE` es **uno** con `executemany` (lista de parametros), no uno por
  fila.

O sea: +1 SELECT fijo por lote, +1 SELECT y +1 UPDATE solo si algo se renombro,
y cero en la siembra inicial (todos los items nuevos → `linked` vacio →
`renames` vacio → return temprano en `identity.py:166`).

El test `test_the_claim_pre_check_still_costs_a_single_query` lo fija comparando
**3 items contra 9** y exigiendo 2 SELECT en ambos casos. Ese es exactamente el
control que hacia falta y no existia antes (el test viejo solo miraba un tamano
de lote). Los dos tests de escalado preexistentes
(`..._do_not_grow_with_the_number_of_items` y `..._of_credits`) siguen verdes
**sin tocarlos**.

### 2.7 `BulkItem.data` sin mutar — cierto

`bulk_load.py:812`: `replace(item, data={**item.data, "slug": aligned[...]})`.
`replace` construye un `BulkItem` nuevo (el dataclass es
`frozen=True, slots=True`) y `{**item.data, ...}` un dict nuevo. El `data`
original no se toca en ningun punto. La reasignacion
`items = await _align_batch_slugs(...)` es local a `bulk_load_items`, asi que la
lista del llamante (`_write_batch`, que la reusa para el fallback per-item)
queda intacta. **Verificado.**

Ademas: el realineado corre en la linea 843, **antes** del bucle de
deduplicacion por slug (lineas 861-892). Orden correcto — si fuera al reves, dos
items del lote podrian colapsar en la fila equivocada. Coincido con el
implementer en que ese orden no esta fijado por ningun test y es el punto fragil
ante un refactor (ver §5, L3).

### 2.8 Docs — describen lo que el codigo hace ahora

- `docs/conventions.md`: la linea "los slugs se generan al persistir el item y
  no cambian" era **falsa** tras este cambio; sustituirla era obligatorio, no
  opcional. La redaccion nueva coincide con `identity.py`, incluidos los tres
  casos de conservacion. Correcto.
- `docs/schema.md` §Item tables: describe el realineado y el `ON CONFLICT`
  intacto. Correcto.
- `docs/schema.md` §Sync cursors: el SQL documentado coincide **literalmente**
  con el compilado que verifique en §2.4, y elimina el matiz "un enlace a otro
  `item_id` cuenta como hecho", que efectivamente ya no es cierto. Correcto.
- `docs/seeding-plan.md` §5.1: lo que hace subir `skipped_links` hoy coincide
  con lo que verifique en §2.5. Correcto.
- `docs/architecture.md`: `shared/identity.py` en el arbol de modulos. Correcto.

---

## 3. Dictamen test por test sobre los tests preexistentes modificados

### 3.1 `tests/shared/test_bulk_load.py`

**`test_batch_still_leaves_an_id_claimed_within_the_same_type_alone`
→ `test_a_tmdb_id_offered_under_a_new_slug_updates_its_own_row`**

**Veredicto: LEGITIMO. Codificaba el bug, literalmente.**

Las aserciones eliminadas eran `intruder = await _movie(db, "bulk-claim-second")`
(existe una segunda pelicula) y
`count(external_ids where item_id == intruder.id) == 0` (y no tiene enlace).
Eso es el sintoma del issue #23 escrito como contrato: dos filas para un mismo
id externo, la segunda irresoluble. No es un test aflojado — las aserciones
nuevas son **mas fuertes**: `renamed.id == claimer.id`,
`count(Movie where slug == "bulk-claim-first") == 0`, `count(links) == 1`.

Lo que el test protegia de verdad —que `uq_external_id` no reviente y que la
ruta per-item coincida con la de lote— se conserva:
`assert same.item_id == claimer.id` sigue ahi. Y el `db.expire_all()` anadido no
oculta nada: es necesario porque el lote escribe con SQL crudo y el identity map
guarda la instancia previa al renombrado; sin el, las aserciones leerian datos
viejos (leerian de mas, no de menos).

El test hermano `test_a_person_claiming_a_tmdb_id_does_not_block_a_movie` —la
mitad de la regla que si sigue vigente, cross-type, issue #20— **no se toca** y
sigue verde.

### 3.2 `tests/shared/test_link_skip_observability.py`

**`test_batch_link_claimed_by_an_existing_row_is_counted`
→ `test_batch_link_claimed_by_an_orphan_row_is_counted`**

**Veredicto: LEGITIMO.** El escenario viejo (renombrado) ya no puede producir
una perdida: comprobado que con el #23 dentro cualquier payload con ese id
externo se redirige a la fila que lo tiene, renombre o no. Mantener el test tal
cual era imposible, no solo incomodo.

El escenario nuevo (enlace huerfano) **es alcanzable de verdad** por el INNER
join de `identity.py:135`. Todas las aserciones del contador son identicas
(`skips.count == 1`, `attempted_item_id`, `claimed_by_item_id`, el holder final).
**Ninguna relajada.**

**`test_sync_games_reports_the_links_it_could_not_write`**

**Veredicto: LEGITIMO**, mismo cambio de escenario, y con una compensacion
explicita: el escenario que se va (renombrado end-to-end sobre `sync_games`) se
recupera en el archivo nuevo como
`test_sync_games_renaming_a_game_updates_its_row`, que asserta
`skipped_links == 0`, fila unica y enlace conservado. El caso no se pierde de
cobertura: **cambia de veredicto y se sigue afirmando**, que es exactamente lo
correcto. Las aserciones del contador (`skipped_links == 1`,
`count(links del item fresco) == 0`) no cambian.

**`test_the_claim_pre_check_still_costs_a_single_query`**

**Veredicto: LEGITIMO y mas estricto que antes.** No es un presupuesto aflojado
de 1 a 2 "porque ahora hay otra query". El test:

1. sigue exigiendo que el pre-check sea **exactamente 1**, identificado por su
   proyeccion (`SELECT external_ids.item_type` + `external_ids.item_id`);
2. exige que la resolucion de identidad sea **exactamente 1**, identificada por
   `JOIN movies`;
3. **anade** lo que antes no existia: que el numero no crezca con el tamano del
   lote, corriendo 3 items y 9 y exigiendo `== 2` en los dos.

Sube el numero absoluto en 1 (justificado y verificado en §2.6) y a cambio fija
la propiedad que de verdad importa a la ruta bulk. Aprobado sin reservas.

### 3.3 `tests/test_openlibrary_dump_seeding.py`

**`test_an_external_id_that_cannot_be_linked_is_reported`**

**Veredicto: LEGITIMO.** Identico razonamiento que 3.2. Aserciones del contador
y de `_exit_code(summary) == 2` intactas; solo cambia quien tiene la terna
(`stale.id` → `orphan_item_id`). Los imports de `upsert_external_id` y
`datetime` se retiran porque dejan de usarse — coherente, y `ruff` lo confirma.

### 3.4 `tests/test_admin_sync.py` (2 tests)

**Veredicto: LEGITIMO y minimo.** No se toca ni una asercion. Se anade a dos
sesiones `AsyncMock` locales el mismo stub de `execute` que **ya existia** en
`_mocked_session_factory` del mismo archivo, porque la ruta per-item emite ahora
un SELECT de identidad y un hijo autogenerado de `AsyncMock` haria de `.all()`
una corrutina. Es adaptacion de andamiaje, no cambio de contrato. El comentario
explica el porque en ambos sitios.

**Conclusion: los 6 tests modificados pasan el filtro. Ninguno afloja una
asercion para que pase el arreglo.**

---

## 4. Verificacion independiente por mutacion

No me fie de la tabla §5 del informe; reproduje tres mutaciones yo mismo y
restaure el arbol despues (`md5sum` de `identity.py` identico al original,
`git diff --stat` sin cambios respecto a lo entregado):

| Mutacion | Resultado propio | Coincide con el informe |
|---|---|---|
| `align_slugs_to_external_ids` devuelve `{}` siempre | **14 de 17 fallan** | si (el informe decia 12 — muerde mas, no menos) |
| `if owner is not None and owner != item_id:` → `if False:` | falla `test_a_rename_into_a_slug_another_item_owns_keeps_the_old_slug` | si |
| `model.id.is_(None)` → `ExternalId.id.is_(None)` (revertir el #25) | falla `test_a_target_whose_triple_points_at_no_item_stays_workable` | si |

La tercera es la importante: confirma que el test del #25 **no pasaria sin el
cambio**, o sea que el `LEFT JOIN` esta realmente ejercitado y no es decorativo.

La segunda confirma tambien la observacion del propio implementer: sin la
asercion sobre el log, esa mutacion sobrevivia porque el savepoint produce las
mismas filas. El test discrimina la comprobacion del rescate. Bien visto.

---

## 5. Hallazgos por severidad

### Bloqueantes
Ninguno.

### Medios
Ninguno.

### Bajos / observaciones (no exigen cambios en esta rama)

**L1 — El `except IntegrityError` del savepoint es mas ancho que el `UPDATE`
que protege.** `identity.py:207-226`: al salir de `session.begin_nested()`,
SQLAlchemy hace flush del estado ORM pendiente *dentro* del savepoint. Si ese
flush —de objetos ajenos al renombrado, p. ej. en la cadena on-demand que llama
`upsert_*` con una sesion con pendientes— lanzase `IntegrityError`, se tragaria
el error, se descartaria esa escritura y se loguearia "renames rolled back".
Ventana estrechisima (hace falta renombrado **y** estado pendiente conflictivo)
y el estado resultante sigue siendo consistente, por eso no bloquea. Si se
quiere cerrar: un `await session.flush()` explicito antes de abrir el savepoint
deja dentro solo el `UPDATE`.

**L2 — `is_new` del fan-out de busqueda se vuelve optimista en el renombrado.**
`search/service.py:173-185` calcula `is_new` mirando si el slug **propuesto**
existe, antes del upsert. Con un renombrado el slug nuevo no existe → `is_new`
sale `True` sobre una fila que si existia → se vuelven a pedir y reescribir los
credits. No es perdida de datos (`credits` hace upsert sobre `uq_credit`) ni
duplica nada; el coste es una llamada extra a la fuente por item renombrado en
esa ruta. Correcto no haberlo tocado aqui, pero conviene tenerlo anotado.

**L3 — El orden "realinear antes de deduplicar" no esta fijado por ningun
test.** El propio implementer lo senala (§9.3) y lo confirmo: el resultado si
esta cubierto, el *orden* no. Un refactor futuro que mueva `_align_batch_slugs`
despues del bucle de dedup por slug pasaria los tests y colapsaria items del
lote en la fila equivocada. Candidato a comentario-ancla o a un test de orden en
un issue aparte.

**L4 — La DB de dev conserva los duplicados historicos.** Como dice el informe
§4.1, `series.id=1265` seguira sin enlace. Es consecuencia aceptada de la
decision de producto (produccion se borra entera antes de la siembra); se anota
solo para la QA manual: **no** interpretar esa fila como fallo del arreglo.

**L5 — Recomendacion operativa que conviene no perder.** Informe §4.1: al vaciar
produccion hay que truncar `external_ids`, `credits` y `seed_targets` **en el
mismo golpe** que las cuatro tablas de items. Si quedan `external_ids`
huerfanos, con el #25 dentro los targets vuelven a `pending` (visible, que es
mejor que antes) pero el id externo queda bloqueado hasta que se borre la fila.
Merece una linea en `docs/seeding-plan.md` o en el runbook de la siembra.

---

## 6. Incidencia durante la verificacion (no imputable a la rama)

**Mi primera ejecucion de `bash init.sh` fallo**: `506 passed, 942 errors in
242.46s`, todos los errores en el setup del fixture `db_engine` con
`asyncpg.exceptions.DeadlockDetectedError` sobre el `TRUNCATE` de
`tests/conftest.py:139`.

Diagnostico: `db_engine` es **session-scoped** y ese `TRUNCATE` corre **una sola
vez** al arrancar la suite; al morir, envenena el fixture y arrastra a todos los
tests que dependen de `db` (los 506 que pasaron son los que no tocan DB). El
deadlock exige otro backend concurrente (`Process 33387` contra `33391`), y una
suite serial no lo produce sola: fue una conexion externa con transaccion
abierta en el momento del arranque. Comprobado a posteriori: contenedor
`backlogg-db` sano (`Up, healthy`), `pg_stat_activity` sin conexiones colgadas,
ningun `pytest` vivo.

**No reproducible: las tres ejecuciones siguientes dieron 1448 passed en ~31 s.**
Queda documentado por transparencia, no como hallazgo contra la rama.

---

## 7. Discrepancias entre el informe y el codigo

Contrastadas todas las afirmaciones verificables del informe. Solo dos
diferencias, ambas a favor del cambio:

1. §5, mutacion M0: el informe dice "12 de 17 fallan"; en mi ejecucion fallan
   **14 de 17**. Los tests muerden mas de lo que el informe declara.
2. §1 habla de "12 call sites on-demand"; conte 13 contando `trending` y el
   benchmark. Diferencia de recuento, no de cobertura: todos pasan el id.

Todo lo demas —el orden dentro de `bulk_load_items`, la ausencia de mutacion de
`BulkItem.data`, el coste por lote, el SQL del #25, los tres casos de colision,
el `ValueError` de `_ITEM_MODELS`, y que `bruno/`, `issues_list.json` y
`progress/current.md` no se tocan— coincide con lo que hace el codigo.

---

## 8. Output de `bash init.sh`

Ejecutado por el reviewer. Se omiten las lineas
`warning: The tool.uv.dev-dependencies field ... is deprecated` (preexistentes,
no dependen de esta rama) y los codigos de color ANSI.

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
311 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [  4%]
........................................................................ [  9%]
........................................................................ [ 14%]
........................................................................ [ 19%]
........................................................................ [ 24%]
........................................................................ [ 29%]
........................................................................ [ 34%]
........................................................................ [ 39%]
........................................................................ [ 44%]
........................................................................ [ 49%]
........................................................................ [ 54%]
........................................................................ [ 59%]
........................................................................ [ 64%]
........................................................................ [ 69%]
........................................................................ [ 74%]
........................................................................ [ 79%]
........................................................................ [ 84%]
........................................................................ [ 89%]
........................................................................ [ 94%]
........................................................................ [ 99%]
........                                                                 [100%]
1448 passed in 30.86s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Ejecuciones: 4 en total — 1 fallo no reproducible por deadlock externo (§6) y
**3 verdes consecutivas con 1448 passed**, que confirman la cifra del informe.

---

## 9. Cambios requeridos

Ninguno. **APPROVED.**

Para el leader, al cerrar:

- `issues_list.json` → marcar **#23** y **#25** como `resolved` con
  `resolution_ref` a esta rama. Ambos piden verificacion antes de cerrar, y la
  natural es la QA manual sobre la DB de dev: forzar un renombrado de un item
  enlazado y comprobar (a) una sola fila, (b) slug nuevo, (c)
  `skipped_links == 0`; y un `seed_target` con enlace huerfano, comprobando que
  vuelve a `pending` y acaba en `unlinkable`.
- El issue **#24** (identidad de `people`) sigue abierto y es hoy la fuente
  principal de `skipped_links`; conviene tenerlo presente al leer el panel de la
  siembra para no atribuir a esta rama lo que mide aquello.
- Considerar un issue de una linea para **L3** (fijar el orden realineado →
  dedup con un test) y otro para la limpieza de enlaces huerfanos, que el
  implementer deja explicitamente fuera (§7 de su informe).
