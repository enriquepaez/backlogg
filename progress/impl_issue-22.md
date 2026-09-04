# Informe de implementación — issue #22

**Tarea:** instrumentar la pérdida silenciosa de enlaces en los dos caminos de
escritura de `external_ids`.
**Rama:** `fix/external_ids_skipped_link_observability`
**Fecha:** 2026-09-04
**Estado:** implementado y verificado — `bash init.sh` verde, **1239 tests**
(1220 previos + 19 nuevos).

---

## 1. Archivos tocados

### Código de producción

| Archivo | Qué cambia |
|---|---|
| `backlogg/shared/external_ids.py` | Nuevo colector (`LinkSkip`, `LinkSkipCollector`, `collect_link_skips`, `record_link_skip`, `MAX_TRACKED_LINK_SKIPS`) sobre `ContextVar`. `upsert_external_id` distingue idempotencia de robo de enlace |
| `backlogg/shared/bulk_load.py` | `_upsert_external_ids`: el `SELECT` de `claimed` lee también `item_id` (misma query, una columna más) y aplica la misma regla; la deduplicación **dentro** del lote también cuenta |
| `backlogg/scheduler/jobs.py` | `_sync_tmdb_type`, `sync_books`, `sync_games` y `sync_missing_credits` abren el colector, propagan `skipped_links` al `dict` de retorno y a la línea de log de cierre. Docstring de cabecera actualizado |
| `backlogg/admin/schemas.py` | `skipped_links: int = 0` en `SyncResponse` |
| `scripts/backfill_sync.py` | Agrega `skipped_links` a lo largo de las iteraciones, lo saca en el log por iteración, en el resumen final y en el `dict` de retorno (ver §5, decisión que va un paso más allá de la letra del plan) |

### Documentación

| Archivo | Qué cambia |
|---|---|
| `docs/api.md` | El ejemplo de respuesta de `POST /v1/admin/sync/{type}` incluye `people_errors` y `skipped_links`; nueva entrada explicando qué significa y por qué no cuenta en `errors` |
| `docs/seeding-plan.md` | Nueva §5.1 «Qué mirar mientras corre (panel de instrumentos)»: tabla de los tres contadores, qué hacer si `skipped_links` sube, y la limitación conocida de `seed_targets` |

### Tests

| Archivo | Qué cambia |
|---|---|
| `tests/shared/test_link_skip_observability.py` | **Nuevo.** 15 tests (detalle en §4) |
| `tests/test_admin_sync.py` | +2: el campo llega a la respuesta HTTP; un job que no lo reporta sigue devolviendo 200 con 0 |
| `tests/test_backfill_sync.py` | +2: agregación a lo largo del bucle; un resultado sin la clave no rompe |
| `tests/shared/test_bulk_load.py` | Ajuste del helper `_people_lookup_statements` (ver §6, hallazgo colateral) |

`bruno/`: **sin cambios**. No hay endpoint nuevo y ningún `.bru` fija el cuerpo
esperado del sync — los cuatro `Sync *.bru` no tienen bloque `tests` ni
aserciones sobre el body. Verificado con `grep -rn "res.body\|tests {" bruno/Admin/`.

Ninguna migración Alembic: el issue es de observabilidad, el esquema no cambia.

---

## 2. Decisiones

### 2.1 El colector loguea siempre; solo *cuenta* dentro de un bloque activo

`record_link_skip()` emite el `logger.warning` incondicionalmente y solo
incrementa si hay un `LinkSkipCollector` en el `ContextVar`. La alternativa
—loguear en cada llamador— habría dado dos formatos de mensaje distintos
(por ítem y por lote) para el mismo evento. Centralizarlo garantiza que la
línea siempre nombra la terna, el pretendiente y el reclamante, que es lo que
la hace accionable: sin los dos `item_id` el log dice que se perdió algo pero
no qué fila mirar.

El coste para el tráfico on-demand (búsqueda, ficha, `/similar`) es una lectura
de `ContextVar` y un `return`. Sin colector no falla ni cuenta nada.

### 2.2 Idempotencia vs. robo de enlace: el discriminante es `item_id`

Los dos casos caen en la misma rama `existing_row is not None`:

- `existing_row.item_id == item_id` → la misma persona de TMDB en cast y crew,
  o un tramo re-ejecutado. **No se cuenta.** Contarlo convertiría el número en
  ruido y nadie lo miraría, que es justo lo que hay que evitar.
- `existing_row.item_id != item_id` → el ítem pretendiente se queda sin enlace
  para siempre. **Se cuenta y se loguea.**

Se mantiene «gana el primero»: cambiar el dueño del enlace es una decisión de
datos, no de instrumentación (ver §7).

### 2.3 El camino batch cuenta **dos** clases de salto

`_upsert_external_ids` descarta filas en dos sitios y ambos son pérdidas reales
cuando el `item_id` difiere:

1. **Contra fila preexistente** (`claimed`): el `SELECT` ahora proyecta también
   `item_id`. Es **la misma consulta con una columna más**, no un round trip
   extra — el presupuesto de round trips es la razón de existir del módulo, y
   pagar la instrumentación con lo instrumentado habría sido mal negocio. Hay un
   test explícito que lo vigila (`test_the_claim_pre_check_still_costs_a_single_query`).
2. **Colisión dentro del propio lote** (`by_pair`): dos ítems distintos del
   mismo tipo ofreciendo la misma terna en un solo batch. Esta pérdida **nunca
   tocaba la base de datos**, así que ninguna consulta podía revelarla.

La deduplicación `by_item` (último gana sobre `(item_type, item_id, source)`)
**no** se cuenta: ahí el `item_id` es el mismo, es el mismo ítem cambiando de id
externo, no un enlace robado por otro.

### 2.4 `ContextVar` en vez de cambiar firmas

Ya venía decidido en `progress/current.md` y lo he seguido tal cual.
`upsert_external_id` tiene 11 llamadores y ninguno está en el camino que
reporta. Añadido a lo del plan: el `ContextVar` guarda un **objeto mutable**, así
que las tareas hijas de `asyncio.gather` (las fases de fetch paralelo de
`_sync_tmdb_type` y `sync_missing_credits`) heredan el contexto y escriben en el
mismo colector; lo único que no se propagaría hacia fuera sería un `set()` desde
la tarea hija, y no se hace ninguno. Hay test de aislamiento y anidamiento
(`test_collectors_do_not_leak_into_each_other`).

### 2.5 Lista de detalle acotada, contador exacto

`MAX_TRACKED_LINK_SKIPS = 100`: el `count` es siempre exacto, pero solo se
guardan las 100 primeras tuplas. Un fallo sistemático durante una carga de
118.850 ítems no puede hacer crecer una lista sin límite en memoria, y como todo
salto se loguea igualmente no se pierde información.

### 2.6 Dónde se abre el bloque

En los cuatro jobs, envolviendo el `async with async_session_factory()` (que es
donde ocurre toda la escritura) y leyendo `link_skips.count` justo después. Los
`return` tempranos (fallo al leer la work list, fallo del adaptador, «nada que
hacer») devuelven `skipped_links: 0` explícitamente, para que la clave esté
siempre presente y `SyncResponse` no tenga que adivinar.

---

## 3. Cómo verificarlo a mano

### 3.1 Salto por el camino per-item (psql + shell)

```bash
docker compose up -d
uv run alembic upgrade head
```

```python
# uv run python -c '...' o un scratch script
# 1. Dos películas, una reclama TMDB 424 y la otra lo intenta después.
# 2. Comprobar en psql que la segunda no tiene fila en external_ids:
#    SELECT * FROM external_ids WHERE item_type='MOVIE' AND external_id='424';
# 3. En el log tiene que aparecer:
#    WARNING backlogg.shared.external_ids: external_ids: link skipped — MOVIE
#    (TMDB, 424) wanted by item_id=<B> is already claimed by item_id=<A>
```

Los tests `test_a_link_claimed_by_another_item_is_counted` y
`test_a_skipped_link_is_logged_with_both_item_ids` hacen exactamente esto contra
la DB real, así que la comprobación manual es opcional.

### 3.2 El contador llega al endpoint

Con la app levantada y `ADMIN_API_KEY` en el entorno:

```bash
curl -s -X POST "$BASE/v1/admin/sync/game" -H "X-API-Key: $ADMIN_API_KEY" --max-time 600 | jq
```

El body debe traer ahora la clave `skipped_links` (0 en un catálogo sano). Los
cuatro tipos la traen; para `game` viene del job y para cualquier job que no la
reporte, del default del schema.

### 3.3 Escenario end-to-end reproducible

`tests/shared/test_link_skip_observability.py::test_sync_games_reports_the_links_it_could_not_write`
monta el caso realista: el juego de IGDB 9300001 se ingirió cuando su nombre
producía el slug `link-skip-game-old`; se ha renombrado, así que el tramo escribe
una **segunda** fila con el slug nuevo que nunca podrá quedarse el id externo.
Antes el job devolvía `errors: 0` y no había forma de enterarse; ahora devuelve
`skipped_links: 1`.

### 3.4 Sin regresión de round trips

```bash
uv run pytest tests/shared/test_bulk_load.py -q -k "round_trips or single_query"
uv run pytest tests/shared/test_link_skip_observability.py -q -k roundtrip
```

### 3.5 Migración up/down

No aplica: esta rama no añade migraciones. `alembic upgrade head` /
`alembic downgrade -1` siguen comportándose igual que en `main`.

---

## 4. Cobertura de tests

`tests/shared/test_link_skip_observability.py` (15):

**Camino per-item**
1. `test_relinking_the_same_item_is_idempotent_and_counts_nothing` — el caso para
   el que se escribió el pre-check no aparece en el contador.
2. `test_a_link_claimed_by_another_item_is_counted` — el salto se cuenta, el
   detalle nombra terna/pretendiente/reclamante, gana el primero, y el
   pretendiente queda con **cero** filas en `external_ids`.
3. `test_a_skipped_link_is_logged_with_both_item_ids` — la línea de log tiene los
   dos `item_id`.
4. `test_a_person_and_a_movie_sharing_a_tmdb_id_is_not_a_skip` — el arreglo del
   issue #20 no se re-reporta como pérdida.

**No-op fuera del colector**
5. `test_upsert_outside_a_collector_still_returns_the_incumbent` — sin colector no
   falla, devuelve lo mismo, y un colector abierto después empieza en 0.
6. `test_record_link_skip_without_a_collector_is_a_no_op`.
7. `test_collectors_do_not_leak_into_each_other` — anidamiento y reset del token.
8. `test_the_detail_list_is_capped_but_the_count_is_not`.

**Camino batch**
9. `test_batch_link_claimed_by_an_existing_row_is_counted`.
10. `test_rerunning_the_same_batch_counts_no_skip` — idempotencia con people incluidas.
11. `test_two_items_of_one_batch_fighting_over_a_triple_are_counted` — colisión
    dentro del propio lote.
12. `test_the_same_item_offered_twice_in_a_batch_is_not_a_skip` — misma persona en
    dos roles.
13. `test_the_claim_pre_check_still_costs_a_single_query` — una sola `SELECT` sobre
    `external_ids`, y proyecta `item_id`.

**Integración**
14. `test_sync_games_reports_the_links_it_could_not_write` — job real contra la DB
    real: `synced: 1`, `errors: 0`, `skipped_links: 1`, y la fila nueva
    verificadamente sin enlace.
15. `test_a_clean_sync_reports_zero_skipped_links` — la clave está siempre.

`tests/test_admin_sync.py` (+2): `test_sync_response_carries_skipped_links`,
`test_sync_response_defaults_skipped_links_to_zero`.

`tests/test_backfill_sync.py` (+2):
`test_backfill_adds_up_the_skipped_links_of_every_iteration`,
`test_backfill_reports_zero_skipped_links_for_a_job_that_omits_the_key`.

---

## 5. Un paso más allá del plan: `scripts/backfill_sync.py`

El plan enumeraba jobs, schema y docs, y no mencionaba el script de backfill.
Lo he incluido igualmente y quiero que quede explícito para que el reviewer lo
juzgue:

La justificación del issue es «el panel de instrumentos de la siembra», y la
siembra se ejecuta con `scripts/backfill_sync.py`, no llamando al job una vez.
Si el job devuelve `skipped_links` pero el script lo lee y lo tira, un backfill
de horas termina reportando «N synced, 0 errors» aunque haya perdido catálogo en
cada iteración — exactamente el fallo que el propio docstring del script
documenta que tuvo con `people_errors` en la feature 85. Además, sin esto la
§5.1 nueva de `docs/seeding-plan.md` estaría documentando un número que el
operador no ve.

El cambio es el análogo estricto de `people_errors` (acumulador, log por
iteración, resumen final, clave del `dict`), usa `.get(..., 0)` para no romper
con jobs que no la reporten, y va con dos tests.

**No** he tocado `.github/workflows/nightly-sync.yml`, que tiene bloques
`::warning::` por tipo leyendo `people_errors` con `jq`. Un bloque equivalente
para `skipped_links` sería natural, pero es superficie de CI, no estaba en el
plan y prefiero que lo decida el leader. Es de tres líneas por tipo si se quiere.

---

## 6. Hallazgos colaterales

### 6.1 Un test existente usaba `external_ids.item_id` como discriminante

`tests/shared/test_bulk_load.py::_people_lookup_statements` identificaba la
consulta de resolución de personas como «la única `SELECT` que lee
`external_ids.item_id`». Al añadir `item_id` al pre-check de `claimed` esa
premisa dejó de ser cierta y el test falló (3 statements en vez de 1). **No es
una regresión**: el test seguía midiendo lo correcto con un filtro que se quedó
obsoleto. Lo he reescrito para distinguir por la proyección (la de personas
empieza por `SELECT external_ids.source`, el pre-check lidera con `item_type`) y
he dejado el porqué en el docstring para que no vuelva a confundir.

### 6.2 El plan menciona `_run_tmdb_slice`; la función se llama `_sync_tmdb_type`

En `backlogg/scheduler/jobs.py` no existe `_run_tmdb_slice`. La función que corre
el tramo de movies/series es `_sync_tmdb_type` (l. 526), y es la que he
instrumentado. `sync_movies` y `sync_series` delegan en ella, así que ambas
heredan `skipped_links`.

### 6.3 `sync_missing_credits` cuenta saltos de **personas**, no de ítems

En ese job el colector recoge los enlaces de `people` que no se pudieron
escribir: el credit sí aterriza, pero esa persona queda irresoluble por id
externo. Lo he documentado en el docstring de la función para que nadie lea el
número como «ítems de catálogo perdidos».

### 6.4 El escenario realista del robo de enlace es el **renombrado**

Buscando cómo reproducirlo end-to-end quedó claro cuál es el mecanismo que de
verdad lo dispara hoy (y me sirvió para el test de integración): un ítem cuyo
título cambia en la fuente genera un slug nuevo, el upsert por slug crea una
**segunda fila** y esa fila ya no puede quedarse el id externo, que sigue en la
antigua. El resultado es un duplicado huérfano permanente. Convendría abrir
issue para el duplicado en sí; el contador ahora al menos lo hace visible.

### 6.5 Fuera de scope, confirmado

No he tocado `_unlinked_targets_stmt` (`backlogg/scheduler/repository.py`). Sigue
dando por convergido un `seed_target` si existe *alguna* fila con su terna, sin
mirar el `item_id`, así que un target robado se cuenta como hecho, no acumula
`attempts` y nunca aparece en `stuck`. Lo he documentado como limitación conocida
al final de la §5.1 de `docs/seeding-plan.md`. **Sigue sin issue propio en
`issues_list.json`** — el plan decía registrarlo si al terminar seguía sin él.

No he tocado `issues_list.json` (el issue #22 sigue `open`): no me corresponde
cerrarlo, espera al reviewer.

---

## 7. Lo que este cambio deliberadamente NO hace

- **No cambia quién se queda el enlace.** Sigue ganando el primero. Decidir el
  dueño legítimo es una decisión de datos y necesita su propio issue.
- **No convierte el salto en `errors`.** El tramo no ha fallado; el ítem se
  escribió. Meterlo en `errors` haría abortar el backfill
  (`synced == 0 and errors > 0`) por una pérdida parcial.
- **No lanza excepción.** Un enlace saltado no puede tumbar una slice de 500.

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
300 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [  5%]
........................................................................ [ 11%]
........................................................................ [ 17%]
........................................................................ [ 23%]
........................................................................ [ 29%]
........................................................................ [ 34%]
........................................................................ [ 40%]
........................................................................ [ 46%]
........................................................................ [ 52%]
........................................................................ [ 58%]
........................................................................ [ 63%]
........................................................................ [ 69%]
........................................................................ [ 75%]
........................................................................ [ 81%]
........................................................................ [ 87%]
........................................................................ [ 92%]
........................................................................ [ 98%]
...............                                                          [100%]
1239 passed in 29.40s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(La línea `warning: The tool.uv.dev-dependencies field ... is deprecated` que uv
imprime en cada invocación se ha omitido; es preexistente y no depende de esta
rama.)

---

## 9. Cierre de hallazgos del reviewer (H1 y H4)

Veredicto **APPROVED** con 4 hallazgos. El leader me devolvió H1 y H4 para
cerrarlos en esta rama; H2 y H3 los gestiona él. Verificación final:
`bash init.sh` verde, **1241 tests** (1239 + 2 nuevos).

### 9.1 H1 — el guard anti-falso-positivo intra-lote ya tiene test

**El hallazgo era correcto y mi §4 item 12 estaba mal atribuido.**
`test_the_same_item_offered_twice_in_a_batch_is_not_a_skip` verifica el
contrato observable, pero no llega a `elif incumbent[1] != row[1]`
(`backlogg/shared/bulk_load.py:643`): los enlaces de personas se construyen
desde `slug_of_key`, un dict con clave `(source, external_id)`, así que la misma
persona en dos roles nunca produce dos filas en `by_pair`.

**La reproducción que sugirió el reviewer tampoco llega a la rama.** Antes de
escribir nada la probé (dos `BulkItem` con el mismo slug y el mismo
`external_id` a través de `bulk_load_items`): `bulk_load_items` **deduplica por
slug antes** de construir sus filas (`bulk_load.py:823-830`, «Same natural key
twice in one batch… replace instead of appending»), así que solo sobrevive un
item, `rows` tiene una sola fila y `by_pair` no ve colisión. Medido:
`written=1, count=0` **tanto con el guard intacto como con `elif True`** — el
mutante seguía vivo.

Conclusión: **ningún caller de producción puede alcanzar hoy esa rama.**
`bulk_load_items` deduplica por slug; `_resolve_people` deduplica por
`(source, external_id)`. Es un guard defensivo. Para cubrirlo de verdad hay que
atacar `_upsert_external_ids` directamente, que es lo que he hecho.

Dos tests nuevos en `tests/shared/test_link_skip_observability.py`, ambos
llamando al helper con un `_Staging(db)` propio:

- `test_an_exact_duplicate_row_inside_one_batch_is_not_a_skip` — la misma terna
  **y** el mismo `item_id` dos veces: `count == 0`, y la fila queda en el
  incumbente.
- `test_two_items_fighting_over_a_triple_inside_one_batch_are_counted` — la
  misma llamada con un solo campo cambiado (`item_id` distinto): `count == 1`.

Están al mismo nivel a propósito: entre los dos fijan la rama a `item_id` y a
nada más, así que romper la condición en cualquier dirección hace fallar uno.
El docstring del primero explica por qué se ataca el helper directamente y por
qué el guard importa aunque hoy sea inalcanzable: una respuesta equivocada aquí
reportaría pérdidas fantasma, y un operador que aprende que el número miente
deja de mirarlo — peor que no tener contador.

**Evidencia de la mutación** (criterio de aceptación de H1):

```
### baseline (guard intacto)
$ uv run pytest tests/shared/ tests/test_admin_sync.py tests/test_backfill_sync.py -q
91 passed in 1.26s

### mutación:  elif incumbent[1] != row[1]:   ->   elif True:
$ uv run pytest tests/shared/ tests/test_admin_sync.py tests/test_backfill_sync.py -q
>       assert skips.count == 0
E       AssertionError: assert 1 == 0
E        +  where 1 = LinkSkipCollector(count=1, skips=[LinkSkip(item_type='MOVIE',
E            source='TMDB', external_id='9200007', attempted_item_id=59,
E            claimed_by_item_id=59)]).count
FAILED tests/shared/test_link_skip_observability.py::test_an_exact_duplicate_row_inside_one_batch_is_not_a_skip
1 failed, 90 passed in 1.32s
```

Mutación inversa, para descartar que el test nuevo pase por accidente:

```
### mutación:  elif incumbent[1] != row[1]:   ->   elif False:
FAILED ...::test_two_items_of_one_batch_fighting_over_a_triple_are_counted
FAILED ...::test_two_items_fighting_over_a_triple_inside_one_batch_are_counted
2 failed, 15 passed in 0.51s
```

Ambas mutaciones **revertidas**; `backlogg/shared/bulk_load.py:643` vuelve a ser
`elif incumbent[1] != row[1]:`, verificado con `sed -n '643p'` y con el
`init.sh` final.

### 9.2 H4 — los dos nits

- `backlogg/shared/external_ids.py`: `MAX_TRACKED_LINK_SKIPS` añadido a
  `__all__` (primero de la lista, que es donde ruff/isort ordena las mayúsculas).
- `tests/shared/test_link_skip_observability.py`: la aserción del log ya no usa
  subcadena. Ahora usa dos regex ancladas con `\b` sobre las frases distintivas
  (`wanted by item_id=<N>\b` y `claimed by item_id=<N>\b`), con un comentario
  explicando por qué. Comprobado que el ancla hace su trabajo: contra el mensaje
  real con `item_id=12`, el chequeo antiguo `"item_id=1" in msg` daba `True` y
  el nuevo `wanted by item_id=1\b` da `False`, mientras que `=12` y `=345`
  siguen matcheando.

### 9.3 Lo que NO he tocado

Según la instrucción del leader: `.github/workflows/nightly-sync.yml`,
`_unlinked_targets_stmt` (`backlogg/scheduler/repository.py`),
`issues_list.json` y la deduplicación `by_item` de `_upsert_external_ids` (H2,
el falso negativo real que va a issue propio) quedan **sin tocar por mí**.

⚠️ Aviso de estado del árbol de trabajo: `.github/workflows/nightly-sync.yml`
aparece como modificado en `git status`, con cuatro bloques `::warning::` que
leen `.skipped_links` con `jq` (uno por tipo). **Ese cambio no es mío** — yo lo
había dejado explícitamente fuera en la §5 de este informe y no he escrito en
ese archivo en ningún momento. Lo señalo para que el leader lo reconozca como
suyo antes del commit y no lo tome por un desvío del scope del implementer.

### 9.4 Corrección al §4 de este informe

El item 12 de la lista de cobertura (`test_the_same_item_offered_twice_in_a_batch_is_not_a_skip`)
está descrito como cobertura del guard intra-lote y **no lo es**: cubre el
contrato observable a través de `bulk_load_items`. La cobertura real del guard
son los dos tests de §9.1. Dejo el item 12 en su sitio porque el test sigue
siendo válido, pero que conste la corrección.

### 9.5 Output final de `bash init.sh`

```
── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
300 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [  5%]
........................................................................ [ 11%]
........................................................................ [ 17%]
........................................................................ [ 23%]
........................................................................ [ 29%]
........................................................................ [ 34%]
........................................................................ [ 40%]
........................................................................ [ 46%]
........................................................................ [ 52%]
........................................................................ [ 58%]
........................................................................ [ 63%]
........................................................................ [ 69%]
........................................................................ [ 75%]
........................................................................ [ 81%]
........................................................................ [ 87%]
........................................................................ [ 92%]
........................................................................ [ 98%]
.................                                                        [100%]
1241 passed in 28.83s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
