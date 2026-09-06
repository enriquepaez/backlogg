# Informe de implementación — issues #23 y #25

**Tarea:** la identidad de un ítem de catálogo pasa a ser su `external_id`
(#23), y `_unlinked_targets_stmt` comprueba a qué `item_id` apunta la terna
(#25). Van en la misma rama porque el #25 sin el #23 es peor que no tocar nada.
**Rama:** `fix/external_id_identity_resolution`
**Fecha:** 2026-09-06
**Estado:** implementado y verificado — `bash init.sh` verde, **1448 tests**
(1431 previos + 17 nuevos).
**Migración Alembic:** ninguna. No cambia el esquema: `identity.py` solo lee
`external_ids` + la tabla del tipo y hace `UPDATE ... SET slug`.

---

## 1. Archivos tocados

### Código de producción

| Archivo | Qué cambia |
|---|---|
| `backlogg/shared/identity.py` | **Nuevo.** La regla del #23 en un solo sitio: `align_slugs_to_external_ids` (por lote), `resolve_item_slug` (por ítem, construido sobre la anterior) y `_slug_owners`. Resuelve la fila por `(item_type, source, external_id)`, realinea su slug y decide qué hacer en las colisiones |
| `backlogg/shared/bulk_load.py` | `_align_batch_slugs` (adaptador fino sobre `identity`) + una llamada al principio de `bulk_load_items`, **antes** de la deduplicación por slug y del COPY. `BulkItem.data` sigue sin mutarse: los ítems realineados se reconstruyen con `dataclasses.replace` |
| `backlogg/{movies,series,books,games}/repository.py` | `upsert_*` acepta `external_id: str \| None = None`; cuando llega, resuelve la identidad antes del `ON CONFLICT ("slug")`. Sin el kwarg el comportamiento es idéntico al anterior |
| `backlogg/{movies,series,books,games}/service.py`, `backlogg/search/service.py`, `backlogg/trending/service.py` | Los 12 call sites on-demand pasan el id externo que ya tenían en la mano para la línea siguiente (`upsert_external_id`) |
| `backlogg/scheduler/jobs.py` | `_write_items_individually` (el fallback per-item de la ruta batch) resuelve la identidad antes de `spec.upsert_item` |
| `backlogg/scheduler/repository.py` | `_unlinked_targets_stmt`: segundo `LEFT JOIN` a la tabla del tipo y `WHERE <item>.id IS NULL` (#25); `_ITEM_MODELS` documentado; `ValueError` explícito para un `item_type` sin modelo |
| `scripts/bench_bulk_load.py` | La ruta per-item del benchmark pasa el id externo, para que siga midiendo lo que hace producción |

### Documentación

| Archivo | Qué cambia |
|---|---|
| `docs/conventions.md` | La regla «los slugs no cambian» era falsa después de esto. Sustituida por: la identidad es el `external_id`, los slugs de ítems **sí** se realinean, y los tres casos en que se conserva el guardado |
| `docs/architecture.md` | `shared/identity.py` en el árbol de módulos |
| `docs/schema.md` | § Item tables: el slug nombra, el id externo identifica. § Sync cursors: la consulta de reanudación lleva el segundo join y se elimina el matiz «un enlace a otro `item_id` cuenta como hecho», que ya no es cierto |
| `docs/seeding-plan.md` | §5.1: qué hace subir `skipped_links` **hoy** (ya no el renombrado) y la limitación conocida de `seed_targets` sustituida por lo que hace ahora y por qué es seguro |

### Tests

| Archivo | Qué cambia |
|---|---|
| `tests/shared/test_external_id_identity.py` | **Nuevo.** 17 tests (detalle en §5) |
| `tests/shared/test_bulk_load.py` | `test_batch_still_leaves_an_id_claimed_within_the_same_type_alone` → `test_a_tmdb_id_offered_under_a_new_slug_updates_its_own_row`: **codificaba el bug**. Ver §6.1 |
| `tests/shared/test_link_skip_observability.py` | Tres tests adaptados: dos escenarios de robo de enlace que eran renombrados pasan a ser el enlace huérfano (§6.2) y el test de presupuesto de round trips pasa a fijar los dos SELECT (§4.3) |
| `tests/test_openlibrary_dump_seeding.py` | `test_an_external_id_that_cannot_be_linked_is_reported`: mismo cambio de escenario |
| `tests/test_admin_sync.py` | Dos sesiones `AsyncMock` locales necesitan `execute` con resultado síncrono, igual que ya hacía `_mocked_session_factory` (la ruta per-item emite ahora un SELECT de identidad) |

`bruno/`: **sin cambios**. No se crea, modifica ni elimina ningún endpoint; los
contratos de respuesta son los mismos.

`issues_list.json`: **sin tocar**. Los dos issues siguen `open` — cerrarlos es
del leader tras el review (`require_verification_to_close: true`).
`progress/current.md`: **sin tocar** tampoco; contiene el plan de la feature 74,
que es otro trabajo en curso, y machacarlo habría destruido contexto ajeno.

---

## 2. Issue #23 — cómo queda la identidad

### 2.1 El mecanismo: realinear el slug, no cambiar la clave del upsert

Los cuatro upserts (y el `INSERT ... SELECT ... ON CONFLICT ("slug")` del lote)
siguen resolviendo por slug. Lo que cambia es que **antes** de ejecutarlos se
busca la fila enlazada a `(item_type, source, external_id)` y se le pone el slug
que propone el payload. El `ON CONFLICT` cae entonces sobre esa misma fila y la
actualiza.

Se eligió esto en vez de reescribir los cuatro upserts para que conflicten
contra `external_ids` porque:

- `uq_external_id` está en **otra tabla**, así que no puede ser el `ON CONFLICT`
  de un `INSERT INTO movies`. Habría que partir la escritura en «busca el id,
  luego UPDATE o INSERT», que son dos round trips por ítem en la ruta que existe
  precisamente por su presupuesto de round trips;
- deja intactos los bloqueos por campo (feature 49), `_NEVER_UPDATED`, el COPY,
  el `RETURNING` que alimenta géneros/credits y el fallback per-item;
- una sola función gobierna las dos rutas, así que el mismo id externo no puede
  significar dos filas distintas según la puerta por la que entre.

### 2.2 Todas las rutas de escritura de catálogo, localizadas

| Ruta | Dónde | Cómo resuelve ahora |
|---|---|---|
| Lote (siembra TMDB, dumps de Open Library, sync nocturno) | `bulk_load_items` | `_align_batch_slugs`, una vez por lote |
| Fallback per-item de un lote que falla | `jobs._write_items_individually` | `resolve_item_slug` por ítem |
| On-demand `GET /{tipo}/{slug}` | `{movies,series,books,games}/service.py` | kwarg `external_id` |
| `/similar` y recomendaciones | mismos services | kwarg `external_id` |
| Fan-out de búsqueda (4 tipos) | `search/service.py` | kwarg `external_id` |
| Trending (movies + series) | `trending/service.py` | kwarg `external_id` |
| Backfill dirigido de credits | `jobs.sync_missing_credits` | no escribe ítems, solo credits: no aplica |
| Edición manual de admin | `admin_update_*` | no viene de una fuente externa: no aplica (y ver 3.3) |

**Lo que no toco: personas.** `people` sigue identificándose por
`uq_people_slug`. Es el issue #24, sigue abierto, y meterlo aquí habría mezclado
dos decisiones de datos distintas. Consecuencia práctica: `skipped_links` sigue
teniendo una fuente viva de sucesos, ver §4.2.

### 2.3 La colisión de slug al renombrar — decisión y porqué

Si el slug nuevo choca con `uq_*_slug`, **no se renombra**: la fila conserva su
slug guardado y la escritura se redirige igualmente a ella (`data["slug"]` pasa
a ser el slug actual de la fila). El ítem se actualiza en su sitio; lo único que
queda desalineado es su URL.

Tres situaciones caen en esa regla, y las tres se loguean:

1. **El slug nuevo ya es de otra fila.** No se le puede robar el nombre: esa
   otra fila es un ítem legítimo, casi siempre con su propio enlace, y
   renombrarla en cascada convertiría un problema en dos. Tampoco vale dejar que
   el `UPDATE` reviente: tumbaría un tramo de 500 ítems por una colisión de
   nombres.
2. **Dos ítems del mismo lote piden el slug nuevo.** No renombra ninguno. Si
   ganara el primero de la lista, el catálogo dependería del orden de llegada de
   un `asyncio.gather`, y ese orden no es estable.
3. **`title` bloqueado por un admin** (feature 49). El slug se deriva del
   título, así que un título curado a mano no puede ser re-sluggeado por la
   fuente. Lo que el bloqueo **no** puede hacer es mandar el payload a otra
   fila: la identidad sigue resolviendo, y por eso el ítem tampoco se duplica.

**Descartadas y por qué:**

- *Sufijo de desambiguación* (`titulo-2010-2`, `titulo-2010-tmdb-284753`): genera
  slugs que cambian sin que cambie nada en la fuente (el sufijo depende de qué
  otro ítem hubiera entrado antes), y ensucia la URL del ítem *renombrado* por
  culpa de un tercero. Además no elimina el caso: dos renombrados simultáneos al
  mismo destino vuelven a competir por el sufijo.
- *Renombrar en cascada al ocupante*: multiplica escrituras y puede encadenarse.
- *Dejar el `IntegrityError` subir*: en el lote se pierde el tramo entero (se
  reprocesa per-item, ~50x más lento) y en on-demand es un 500.

**Y además, la carrera.** La comprobación y el `UPDATE` no son atómicas: otro
escritor puede coger el slug en medio. El `UPDATE` va dentro de un `SAVEPOINT`;
si salta `IntegrityError` se deshace, **todos** los renombrados de esa llamada
conservan su slug (que es exactamente el estado real de la base) y la función
devuelve eso, así que el upsert posterior sigue cayendo en la fila correcta. Un
renombrado que pierde una carrera no puede convertirse en un 500. Hay test, y
muta (§5, M4).

### 2.4 Coste

Ruta de lote: **+1 SELECT por lote** siempre (la resolución de identidad), y
+1 SELECT +1 UPDATE **solo si algo se renombró** — es decir, cero en la siembra
inicial, donde todos los ítems son nuevos. No depende del tamaño del lote, y hay
test que lo fija comparando 3 ítems contra 9.

Ruta on-demand y fallback per-item: +1 SELECT por ítem (los mismos +1/+1 cuando
hay renombrado). Es la ruta que ya gasta 35-75 round trips por ítem.

---

## 3. Issue #25 — por qué ahora es seguro

### 3.1 Qué comprueba exactamente

`SeedTarget` **no tiene** columna `item_id`: un target solo conoce
`(item_type, source, external_id)`. Así que «comprobar `item_id`» solo puede
significar una cosa comprobable: que la fila de `external_ids` con esa terna
**llegue a un ítem vivo del tipo del target**. Se implementa encadenando un
segundo `LEFT JOIN` (`external_ids.item_id` → `movies`/`series`/`books`) y
pidiendo `<item>.id IS NULL`, que cubre los dos casos de una vez —no hay fila de
enlace, o la hay y no apunta a nada— porque un NULL del primer join solo puede
producir NULL en el segundo.

### 3.2 Por qué «otro `item_id`» se reduce a eso (verificado en el código real)

Con el #23 dentro, si la terna existe y apunta a una fila viva, **esa fila es el
ítem que el target sembraba**, por construcción: cualquier escritura que traiga
ese id externo se resuelve sobre esa misma fila (`align_slugs_to_external_ids`),
la renombre o no. Repasé los caminos por los que un ítem podría acabar con la
terna de otro:

- *Renombrado*: ya no crea segunda fila. Cubierto por los tests del #23.
- *Colisión de slug entre dos ids externos distintos* (dos títulos que foldan
  igual): las dos payloads caen en la misma fila y `uq_item_source`
  (`ON CONFLICT ... DO UPDATE SET external_id`) hace que la fila tenga **un solo**
  id externo a la vez. El target del otro id se queda **sin fila de terna**, o
  sea `pending`, que es la respuesta correcta; gasta sus `attempts` y se retira
  como `unlinkable`. Ese es el caso que `_retired_clause` ya documenta y acota.
  No hay reintento eterno: `TMDB_SEED_MAX_ATTEMPTS` lo cierra.
- *Enlace huérfano* (fila de `external_ids` apuntando a un ítem borrado): el
  target vuelve a la work list — que es justo lo que este issue quiere— y
  también se retira por `attempts` si el huérfano no se limpia. Antes
  desaparecía del panel sin haber sembrado nada.

Conclusión: reabrir un target con la comprobación puesta **no** puede degenerar
en el reintento infinito que este issue temía, porque la única forma de volver a
la lista es no tener enlace útil, y la retirada por `attempts` sigue en pie.
Sin el #23 esto no se sostenía: un renombrado dejaba la terna permanentemente en
manos de una fila que el target ya nunca iba a escribir.

### 3.3 Efecto observable

Un target que antes desaparecía en silencio ahora: vuelve a `pending` → se
reintenta → acumula `attempts` → a las `TMDB_SEED_MAX_ATTEMPTS` pasadas
concluyentes entra en `unlinkable`, y por tanto en `stuck`, con su
`logger.warning` de cierre de tramo. Pasa de invisible a numerado.

---

## 4. Impacto sobre lo que ya existía

### 4.1 La premisa «producción se borra antes de la siembra»

Se sostiene en todo lo que he tocado. **No hay migración de reconciliación** y
no se preserva ningún slug antiguo. Dos matices que el leader debería tener
presentes, ninguno bloqueante:

- **La DB de dev no se va a borrar** (la usa la QA manual). Ahí sí quedan los
  duplicados históricos —incluida la serie 284753, `series.id=4` y `1265`—, y
  este cambio **no los reconcilia**: la fila 1265 seguirá sin enlace hasta que
  alguien la borre a mano. Lo que sí pasa es que el 4 se actualiza y no se
  generan más.
- **Un `external_ids` huérfano bloquea el id para siempre**, y el borrado de
  producción lo puede fabricar si se vacían las tablas de catálogo sin vaciar
  `external_ids`. La recomendación operativa es truncar `external_ids`,
  `credits` y `seed_targets` en el mismo golpe que las cuatro tablas de ítems.
  Con el #25 dentro eso ya no se esconde: los targets vuelven a `pending` en vez
  de contarse como hechos.

### 4.2 `skipped_links` (issue #22) no se rompe, pero cambia de causa

El contador sigue vivo y sigue contando lo mismo (`item_id` distinto = pérdida,
`item_id` igual = idempotencia). Lo que cambia es **qué lo dispara**: el
renombrado, que era la causa medida en la QA del #22, ya no produce ninguna
pérdida y ahora reporta 0. Siguen contando:

1. **Personas** (`_resolve_people` → `_upsert_external_ids`): la identidad de
   `people` sigue siendo el slug (issue #24), así que dos personas distintas que
   folden igual siguen robándose el enlace. Es hoy la fuente principal.
2. **Enlaces huérfanos**: la terna la tiene una fila que no llega a ningún ítem.
3. **Duplicados dentro de un mismo lote**.

Los tests del #22 que usaban el renombrado como escenario se han reescrito sobre
el caso (2), que es real y sigue siendo permanente. Ninguna aserción del
contador se ha relajado.

### 4.3 Presupuesto de round trips del lote

`test_the_claim_pre_check_still_costs_a_single_query` decía «exactamente 1 SELECT
sobre `external_ids` por lote». Ahora son **2** y el test lo dice explícitamente:
identifica cada uno por su proyección (el pre-check lidera con `item_type`; el de
identidad hace `JOIN movies`) y comprueba que ninguno crece con el tamaño del
lote. Los dos tests de escalado (`..._do_not_grow_with_the_number_of_items` /
`..._of_credits`) siguen verdes sin tocarlos, que es la prueba de que el coste es
por lote y no por ítem.

---

## 5. Tests añadidos y evidencia de que muerden

`tests/shared/test_external_id_identity.py`, 17 tests:

**#23 — la fila se actualiza, no se duplica**
1. `test_the_batch_route_follows_the_external_id_when_the_title_changes` — ruta
   de lote: misma `id`, slug nuevo, la fila vieja no existe, un solo enlace,
   `skipped_links == 0`.
2. `test_the_on_demand_route_follows_the_external_id_when_the_title_changes` —
   lo mismo por `upsert_movie(..., external_id=...)`.
3. `test_every_content_type_resolves_by_external_id` (3 casos parametrizados) —
   series/TMDB, books/OPEN_LIBRARY, games/IGDB. Un arreglo aplicado a tres tipos
   de cuatro es la forma exacta de todos los issues de esta familia.
4. `test_the_per_item_fallback_of_the_batch_route_resolves_by_external_id` — el
   fallback corre justo cuando algo ya va mal; si no resolviera, seguiría
   forkando duplicados.
5. `test_the_tmdb_284753_regression` — **el caso medido**, con los dos títulos
   reales y el id 284753, por la misma ruta que lo produjo (el lote de siembra).
6. `test_sync_games_renaming_a_game_updates_its_row` — end to end sobre un job
   real: `skipped_links == 0` y la fila renombrada conserva su enlace.
7. `test_the_on_demand_service_renames_instead_of_duplicating` — la cadena
   on-demand completa (`service.get_movie` con TMDB mockeado), que es lo que
   prueba que el service pasa el id hacia abajo.

**#23 — colisiones**
8. `test_a_rename_into_a_slug_another_item_owns_keeps_the_old_slug` — conserva
   el slug, actualiza en su sitio, el ocupante intacto, y **asserta el log** de
   la comprobación para distinguirla del rescate por savepoint.
9. `test_two_items_of_one_batch_renaming_into_the_same_slug_keep_theirs`.
10. `test_an_admin_locked_title_is_not_renamed_but_still_finds_its_row`.
11. `test_losing_the_race_for_a_slug_is_absorbed_by_the_savepoint` — la carrera,
    reproducida haciendo que `_slug_owners` conteste «libre» sobre un slug que
    no lo está: no propaga, ambas filas sobreviven con sus enlaces.
12. `test_a_link_pointing_at_no_item_decides_no_identity` — un enlace huérfano
    no redirige nada y la pérdida la reporta el contador del #22.

**#25**
13. `test_a_target_whose_triple_points_at_no_item_stays_workable` — sigue en la
    work list, acumula `attempts` y acaba en `unlinkable`/`stuck` en vez de
    desaparecer.
14. `test_a_target_linked_to_its_own_item_is_done` — sin regresión de
    convergencia.
15. `test_a_renamed_seeded_target_stays_converged` — los dos issues juntos: el
    renombrado no devuelve el target a la lista **y** deja una sola fila.

### Mutaciones (todas revertidas y verificadas con `ruff check` + `init.sh` final)

| # | Mutación | Resultado |
|---|---|---|
| M0 | `align_slugs_to_external_ids` devuelve `{}` siempre | **12 de 17 fallan** |
| M1 | `if owner is not None and owner != item_id:` → `if False:` | falla `..._another_item_owns_keeps_the_old_slug` |
| M2 | `if target in contested:` → `if False:` | falla `..._renaming_into_the_same_slug_keep_theirs` |
| M3 | `if _TITLE_LOCK in locked:` → `if False:` | falla `..._admin_locked_title...` |
| M4 | `except IntegrityError:` → `except ValueError:` | falla `..._absorbed_by_the_savepoint` |
| M5 | `_unlinked_targets_stmt` vuelve a `ExternalId.id.is_(None)` | falla `..._points_at_no_item_stays_workable` |

M1 es la razón por la que el test 8 asserta el log: sin esa aserción la mutación
**sobrevivía**, porque el savepoint absorbe el `IntegrityError` y produce las
mismas filas. Era un test que no distinguía la comprobación del rescate.

---

## 6. Tests preexistentes que codificaban el bug

### 6.1 `test_batch_still_leaves_an_id_claimed_within_the_same_type_alone`

Cargaba dos veces el mismo id de TMDB con slugs distintos y **asserta que se
escribían dos películas** y que la segunda se quedaba sin enlace. Es literalmente
el issue #23 escrito como contrato. Reescrito
(`test_a_tmdb_id_offered_under_a_new_slug_updates_its_own_row`) manteniendo lo
que sí seguía siendo cierto —`uq_external_id` no revienta— y explicando en el
docstring qué protegía la regla vieja y por qué protegía lo que no era.

### 6.2 Dos tests del #22 y uno de la siembra de books

`test_batch_link_claimed_by_an_existing_row_is_counted`,
`test_sync_games_reports_the_links_it_could_not_write` y
`test_an_external_id_that_cannot_be_linked_is_reported` usaban el renombrado como
escenario de robo de enlace. Ya no lo es. Los tres pasan al enlace huérfano, que
sigue siendo una pérdida real y permanente, con el docstring diciendo qué cambió
y por qué. Las aserciones sobre el contador son las mismas.

### 6.3 `tests/test_admin_sync.py`

Dos tests montan su propia sesión `AsyncMock` sin `execute`; con el SELECT de
identidad en la ruta per-item, `.all()` devolvía una corrutina. Se les añade el
mismo stub que ya usaba `_mocked_session_factory` en ese archivo, con la nota de
por qué.

---

## 7. Lo que este cambio deliberadamente NO hace

- **No reconcilia duplicados existentes.** Decisión de producto: producción se
  borra antes de la siembra. En dev quedan (ver §4.1).
- **No preserva el slug antiguo** ni deja redirección: `GET /movies/{slug-viejo}`
  de un ítem renombrado da 404 (y, si es un tipo con fallback on-demand, dispara
  una búsqueda en la fuente). Es la consecuencia aceptada de la decisión.
- **No cambia la identidad de `people`** (issue #24, abierto).
- **No limpia enlaces huérfanos.** Adoptar la terna de un `item_id` muerto es
  otra decisión de datos; hoy se reporta (`skipped_links` + `pending`), que es lo
  que permite verla. Si el leader quiere, es un issue nuevo de una línea.
- **No mueve el «gana el primero»** de `upsert_external_id` /
  `_upsert_external_ids`: con la identidad resuelta antes, esa rama solo se
  alcanza en los tres casos de §4.2.

---

## 8. Output de `bash init.sh`

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
1448 passed in 31.70s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(Se omiten las líneas `warning: The tool.uv.dev-dependencies field ... is
deprecated` que uv imprime en cada invocación; son preexistentes y no dependen de
esta rama.)

---

## 9. Qué debería mirar el reviewer con lupa

1. **§2.3, la decisión de la colisión.** Es la única decisión de producto que he
   tomado yo. Si el criterio del usuario fuera «mejor un slug feo que un slug
   desactualizado», el cambio es local a `identity.py` (una rama) más su test.
2. **§3.2, el razonamiento del #25.** Es el corazón del acoplamiento entre los
   dos issues. He enumerado los caminos por los que una terna podría acabar en
   manos de otro ítem; si se me escapa alguno, la conclusión «no puede reintentar
   eternamente» se cae. Sugiero releerlo contra `_upsert_external_ids` (la rama
   `ON CONFLICT ON CONSTRAINT uq_item_source DO UPDATE`, que es la que hace que
   una fila solo tenga un id externo por fuente).
3. **El orden dentro de `bulk_load_items`.** El realineado corre **antes** de la
   deduplicación por slug del propio loader. Si se moviera después, dos ítems del
   lote podrían colapsar en la fila equivocada. No hay test que fije el *orden*
   como tal (sí el resultado); es el punto más frágil ante un refactor futuro.
4. **`_ITEM_MODELS` sin `GAME`.** `_unlinked_targets_stmt` levanta `ValueError`
   para un tipo sin modelo. Hoy solo se llama con MOVIE/SERIES
   (`SEED_TARGET_SOURCES`), pero si algún día se siembran juegos por
   `seed_targets` hay que añadir `Game` ahí — y `get_credit_gaps` comparte el
   diccionario, así que conviene mirar los dos consumidores a la vez.
5. **Mutación de tests, no solo verde.** §5 tiene seis mutaciones con su
   resultado; la M1 es un ejemplo de test que pasaba por la razón equivocada
   antes de añadirle la aserción del log. Vale la pena repetir alguna.
6. **Los tests que he reescrito (§6).** Son la parte que más merece una segunda
   opinión: he cambiado contratos que estaban escritos a propósito. Mi criterio
   ha sido conservar la intención (¿el contador sigue contando? ¿sigue sin
   reventar `uq_external_id`?) y cambiar solo el escenario que ya no puede
   ocurrir.
