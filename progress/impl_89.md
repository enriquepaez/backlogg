# Feature 89 — `credits_people_storage_redesign` (implementación)

Rama `feat/credits_people_storage_redesign`. Alcance ejecutado: **A + B**, tal y
como quedó cerrado en `progress/measure_89.md` §11. No he reabierto ninguna de
esas decisiones.

`bash init.sh` → **exit 0**, 1.458 tests (antes 1.448; +10 netos). Output
completo al final.

---

## 1. Las dos decisiones que el brief me pedía justificar

### 1.1 `smallint` con constante en Python, **no** ENUM nativo

Tres razones, en orden de peso, y las tres están en el docstring de
`backlogg/shared/codes.py`:

1. **Tamaño.** Un valor de ENUM nativo es un `oid`: **4 bytes**. Un `smallint`
   son **2**. Con dos columnas así en 710.772 filas *más* sus copias dentro de
   tres índices, el ENUM cuesta varios MB más para exactamente el mismo
   vocabulario. Esta feature existe porque la base no cabe en 512 MB: cualquier
   empate se rompe por el lado del disco.
2. **Añadir un valor es DDL.** `ALTER TYPE ... ADD VALUE` es una migración y una
   ventana de despliegue; aquí es una línea en un dict.
3. **`item_type` no es local a `credits`.** Vive también como texto en
   `external_ids`, `catalog_search`, `seed_targets`, `sync_cursors`,
   `activity_events`, `library_entries`, `notifications` y `company_credits`.
   Un ENUM nativo solo en `credits` convertiría cada comparación contra esas
   tablas en una cruzada con cast explícito, y convertirlas todas es un cambio
   mucho mayor que el que la feature 89 puede permitirse.

**Cómo evito los «números mágicos repartidos».** El mapeo se aplica en **dos
`TypeDecorator`** (`ItemTypeCode`, `CreditRoleCode`), es decir en la frontera de
persistencia y en ningún otro sitio. El resto del código sigue escribiendo
`Credit.item_type == "MOVIE"` y leyendo `credit.role == "AUTHOR"` sin ver un
número jamás — servicios, repositorios y tests incluidos. La alternativa
(esparcir `ITEM_TYPE_CODES["MOVIE"]` por cada query) es justo lo que el brief
prohibía, y además habría metido un cambio de almacenamiento dentro de la lógica
de negocio. Un valor fuera de vocabulario **lanza**, no se coerce ni se
descarta: hay test (`test_credit_rejects_an_unknown_role`).

### 1.2 `credits` se **reconstruye y se intercambia**, no se altera columna a columna

Tres motivos: `ALTER COLUMN TYPE` reescribe la tabla igual; borrar columnas **no
libera su espacio ni reordena el layout físico**, así que la ganancia de
alineación de los ~7 MB no se materializaría sin un `VACUUM FULL` que no puede
correr dentro de la transacción de la migración; y solo sobrevive el 27 % de las
filas, así que copiarlas es más barato que reescribir las 710.772.

Esto es importante y no es cosmético: **el orden de declaración de las columnas
es el orden físico en Postgres**. Con `smallint, bigint, bigint, smallint` habría
6 bytes de relleno por fila. La tabla nueva declara `item_id, person_id`
(bigint) antes de `item_type, role` (smallint), y la PK va ordenada igual.

---

## 2. Archivos

### Nuevos

| Archivo | Qué es |
|---|---|
| `backlogg/shared/codes.py` | Vocabulario `ITEM_TYPE_CODES` / `CREDIT_ROLE_CODES` + los dos `TypeDecorator`. Único sitio donde texto y número se tocan. |
| `alembic/versions/0037_credits_people_storage_redesign.py` | La migración, con backfill por lotes y `downgrade` best-effort. |
| `tests/test_credits_cast_graph_split.py` | Los cuatro contratos de la feature (ver §5). |
| `bruno/People/Get person by slug — cast-only actor (404).bru` | El 404 documentado. |

### Modificados

| Archivo | Cambio |
|---|---|
| `backlogg/shared/models.py` | `Credit` estrechado (sin `id`, sin `character_name`/`billing_order`, PK natural reordenada, dos `smallint`). `ItemCast` nuevo. |
| `backlogg/shared/credits.py` | `CAST_ROLE` / `GRAPH_ROLES`; `build_cast_payload`, `cast_payload_to_credits`, `upsert_item_cast`, `cast_payload_json`; `get_credits_for_item` ahora **fusiona** las dos tablas. |
| `backlogg/shared/bulk_load.py` | `_load_people_credits` bifurca sobre `CAST_ROLE`. `_coerce` aprende a aplicar el bind processor de un `TypeDecorator` (COPY salta SQLAlchemy). |
| `backlogg/movies/service.py`, `backlogg/series/service.py` | La ruta por ítem escribe `item_cast` para el reparto y `credits` solo para el crew. |
| `backlogg/scheduler/jobs.py` | `_persist_people_individually` (el fallback per-item) toma la misma bifurcación. |
| `backlogg/scheduler/repository.py` | `get_credit_gaps`: `Credit.id` → `Credit.person_id` y **LEFT JOIN también a `item_cast`**. Ver §4.1. |
| `backlogg/recommendations/repository.py` | `select(Credit.id)` → `select(Credit.person_id)` dentro del EXISTS. Nada más; el contrato no se mueve. |
| `backlogg/people/repository.py` | `upsert_credit` sin `RETURNING id` (`ON CONFLICT DO NOTHING` + relectura por clave natural). `_resolve_credits` devuelve `character_name`/`billing_order` a `null`. |
| `backlogg/books/service.py` | Deja de pasar las dos claves muertas a `upsert_credit`. |
| `scripts/bench_bulk_load.py` | Bifurca igual y su `DELETE` en SQL crudo usa el código numérico. |
| `docs/schema.md` | Modelo nuevo **con el razonamiento**: por qué ficha y grafo se separan, `item_cast` entera, y la nota de las dos columnas borradas. |
| `docs/api.md` | Procedencia y orden de `credits[]`; los dos comportamientos de `GET /people/{slug}`. |
| `docs/operations.md`, `docs/seeding-plan.md` | Los dos sitios donde la descripción del hueco de credits o del dimensionado se quedaban obsoletos. |
| `bruno/People/Get person by slug.bru` | Bloques `tests` y `docs`. |
| 12 archivos de `tests/` | Ver §5. |

---

## 3. Cómo quedó el modelo

`credits` = **grafo** (DIRECTOR, CREATOR, WRITER, AUTHOR, SOURCE_AUTHOR).
`item_cast` = **ficha** (una fila por ítem, array JSONB ordenado por billing
order, sin recortar).

```
[{"n": "Timothée Chalamet", "c": "Paul Atreides", "o": 0}, ...]
```

Claves de un carácter porque se repiten ~518.000 veces. `c` y `o` se omiten
cuando no se conocen.

**La bifurcación vive en un solo sitio.** Las tres rutas de escritura (por ítem,
por lotes, y el fallback per-item de `jobs.py`) se bifurcan sobre la misma
constante `CAST_ROLE` de `shared/credits.py`. Deliberadamente **no** bifurqué
dentro de `map_movie_credits`/`map_series_credits`: la capa de mapeo sigue
entregando el reparto intacto, que es lo que necesitaría una futura
re-hidratación (§9 del informe de medición), y las tres fronteras no pueden
divergir porque comparten la regla.

---

## 4. Desviaciones del brief y decisiones que conviene mirar

### 4.1 Añadí un `LEFT JOIN item_cast` a `get_credit_gaps` (no estaba en el brief)

`scheduler/repository.py::get_credit_gaps` es la lista de trabajo del backfill
dirigido (feature 85) y decidía «este ítem no tiene personas» con
`LEFT JOIN credits ... WHERE NULL`. Con B, **una película con reparto pero sin
crew de la allowlist tiene cero filas en `credits`** y estaría perfectamente
ingerida: la query la habría devuelto como hueco en cada run, para siempre,
gastando una llamada a TMDB por ítem y por noche. Ahora la condición es «ni
`credits` ni `item_cast`». Hay test:
`test_gap_query_treats_a_stored_cast_as_covered`.

### 4.2 Las entradas de reparto llegan con `profile_url: null` y un `person_slug` que no resuelve

Es consecuencia directa de la §11.1 del informe («nombre, personaje y orden»),
pero es un cambio **semántico** dentro de una forma que no cambia, y prefiero
señalarlo en vez de que aparezca en la QA:

- **`profile_url`**: guardarlo casi duplicaría el payload (~+60 B por actor: 34
  MB → ~68 MB), que es justo la cifra que la feature intenta bajar, y ningún
  consumidor lo lee — `apps/web/src/components/item-credits.tsx` no lo pinta.
- **`person_slug`**: se deriva del nombre con `slugify` al leer. Para un actor
  de solo-reparto ese slug **no resuelve** (404 por diseño), y en `apps/web`
  solo se usa como key de React. Guardarlo costaría ~18 B por actor por un dato
  que ya no apunta a nada.

Ambos están documentados en `docs/api.md` con una tabla y en el docstring de
`cast_payload_to_credits`. **Si el leader prefiere pagar los MB por conservar
`profile_url`, el cambio es de tres líneas** (una clave más en
`build_cast_payload` y una en el backfill de la migración).

### 4.3 No marqué la feature `in_progress` — no puedo, sin romper `init.sh`

Lo hice al empezar y `init.sh` pasó a fallar: **la feature 74 sigue en
`in_progress` a propósito** (documentado en `progress/current.md`: se cierra
junto al issue #15 cuando la siembra termine) y el harness admite **máximo 1**.
Como `init.sh` en verde es criterio de aceptación y el estado de la 74 no es mío
para tocarlo, dejé la 89 en `pending` y lo reporto aquí. **Decisión del leader.**

### 4.4 Tests que toqué y que quizá quieras mirar dos veces

- **`tests/test_credits_source_author_role.py`**: el bloque protegido (el puente
  cross-type, ~líneas 475-547) **no se ha tocado** y pasa sin cambios. Lo único
  que cambié en ese archivo es el helper `_persisted_roles`, que ahora lee las
  **dos** tablas — la pregunta que hacen esos tests («¿clasificó bien la
  ingesta este crew?») no cambió, solo el sitio donde está la respuesta. Diff:
  +22/-2 líneas, todas en el helper y los imports.
- **`tests/test_person_dedup.py`**: tres tests eran específicamente sobre dedup
  de *actores*. Con B la pregunta desaparece (el reparto nunca llega a `people`),
  así que los invertí: ahora afirman que **no** se crea fila en `people` ni en
  `external_ids` y que el nombre aterriza en `item_cast`. El dedup de crew, que
  sí sigue importando, ya tenía sus propios tests y siguen intactos.
- **`tests/games/test_router.py`**: el test creaba un person credit de GAME con
  `role: "DEVELOPER"`, un rol que la ingesta nunca escribe (games no tienen
  person credits, `docs/schema.md`) y que no está en el vocabulario. Lo pasé a
  `DIRECTOR` y ajusté el nombre y el docstring; con el modelo nuevo el test ya no
  puede llamarse «ordered by billing_order» porque los games no tienen reparto.

### 4.5 `people_written` ahora cuenta reparto + crew

`BulkLoadResult.people_written` alimenta `credits_written` en el resumen de
`sync_missing_credits`, que el operador lee como «¿este run escribió algo?». Si
solo contara filas de `credits`, un ítem cuyas únicas personas son su reparto
saldría como vacío. Cuenta las dos mitades.

---

## 5. Tests

**Nuevos** — `tests/test_credits_cast_graph_split.py`, ocho tests para los cuatro
contratos:

| Test | Qué fija |
|---|---|
| `test_authorship_bridge_survives_for_an_author_who_also_acts` | El puente cross-type de la feature 74, en el caso que la separación podía romper: alguien con credits de las dos clases. |
| `test_a_person_who_directs_and_acts_keeps_the_graph_and_loses_the_cast` | El caso Clint Eastwood, extremo a extremo por HTTP: `/people/{slug}` 200 con la filmografía de dirección entera y **sin** ACTOR; la ficha de la película en que solo actúa **sí** lo muestra. |
| `test_a_cast_only_person_is_a_404` | El 404 documentado. |
| `test_the_detail_page_gets_the_full_cast_in_billing_order` | 30 actores (el máximo medido en producción) desordenados a la entrada: salen completos, en orden, y el crew detrás. Sin recortar. |
| `test_an_item_with_no_cast_returns_only_its_crew` | La lectura fusionada no inventa reparto donde no lo hay (libros). |
| `test_upsert_item_cast_replaces_the_array_wholesale` | Una reingesta reescribe el array, no lo mezcla. |
| `test_a_graph_credit_survives_a_person_rename` | `upsert_credit` sigue siendo idempotente sobre la clave natural. |
| `test_migration_0037_upgrades_and_downgrades_with_data` | **La migración, en los dos sentidos, contra una base con filas.** Ver abajo. |

**El test de migración** crea una base de datos aparte (`backlogg_migration_0037`),
la migra a 0036, la siembra con la forma que importa —una persona solo-reparto,
una solo-crew, una que hace las dos (Eastwood) y un autor de Open Library—,
aplica `0037`, comprueba tipos, códigos, payload, purga de `people` y de
`external_ids`, hace `downgrade` y comprueba **la asimetría**: el grafo vuelve
entero, los ACTOR de Eastwood se reconstruyen desde `item_cast`, y las personas
de solo-reparto siguen sin volver. Tarda ~1,4 s. También lo ejecuté a mano
contra una base de scratch antes de automatizarlo, incluyendo un
`upgrade → downgrade → upgrade` para verificar que el ciclo es estable.

**Modificados**: `tests/shared/test_models.py`, `tests/shared/test_bulk_load.py`,
`tests/shared/test_slug_non_latin_fallback.py`, `tests/people/test_repository.py`,
`tests/people/test_router.py`, `tests/movies/test_routes.py`,
`tests/series/test_routes.py`, `tests/games/test_router.py`,
`tests/books/test_rating_sort.py`, `tests/books/test_similar_service.py`,
`tests/test_backfill_credits_targeted.py`,
`tests/test_credits_source_author_role.py`, `tests/test_person_dedup.py`.

Donde el test seguía preguntando lo mismo pero la respuesta se había mudado de
tabla (`_credits_of`, `_persisted_roles`, `_cast_names`) amplié el **helper** en
vez de reescribir las aserciones: así el diff dice qué cambió de sitio y no
tapa lo que hubiera cambiado de significado.

---

## 6. La migración

`0037_credits_people_storage_redesign.py`. Orden: crear `item_cast` → backfill
del reparto desde los credits ACTOR → registrar en una temp table quién era
**solo** reparto → crear `credits_new` y copiar el grafo → swap y renombrado de
constraints e índices → purgar `people` y `external_ids`.

- **Por lotes de verdad.** Todo paso masivo recorre `item_id` en ventanas de
  20.000 (`_walk_windows`), nunca una sentencia sobre la tabla entera.
- **Atómica.** Las ventanas **no** son transacciones separadas: `alembic/env.py`
  envuelve la corrida entera en una. Un fallo en la ventana 40 revierte las 39
  anteriores. Eso es lo que hace verdad «no se queda a medias».
- **Falla ruidosa ante vocabulario desconocido.** `_assert_known_vocabulary`
  corre **antes** de escribir nada y aborta con la lista de valores ofensivos.
  Descartar en silencio credits que no sé mapear sería perder catálogo dentro de
  una migración cuyo propósito es que el catálogo quepa.
- **La asimetría del `downgrade` está en el docstring**, con nombres y cifras:
  vuelve el esquema entero y el grafo exacto; vuelven los ACTOR cuyo nombre
  todavía casa con una fila de `people` (las ~9.251 personas que dirigen y actúan,
  60.095 credits); **no vuelven** las 175.306 personas de solo-reparto, ni sus
  `external_ids`, ni sus credits, ni el `created_at` de las filas reconstruidas.
  El camino de vuelta real es la reingesta (`--only-missing-credits --recheck`),
  y el docstring lo dice así.

---

## 7. Medición local: antes / después

Contra la DB de desarrollo (`backlogg`, docker compose), 14.861 credits · 11.763
personas · 14.404 external_ids. Es ~2 % del volumen de producción, así que **vale
como validación de que la migración hace lo que dice, no como estimación del
ahorro real**.

| Tabla | Antes | Después de `0037` | Después de `VACUUM FULL` | Filas antes → después |
|---|---|---|---|---|
| `credits` | 3.616 kB | **488 kB** | 488 kB | 14.861 → 2.280 |
| `people` | 3.472 kB | 3.472 kB | **624 kB** | 11.763 → 1.935 |
| `external_ids` | 3.552 kB | 3.552 kB | **1.048 kB** | 14.404 → 4.593 |
| `item_cast` | — | 1.080 kB | 1.080 kB | — → 1.619 |
| **Suma** | **10.640 kB** | 8.592 kB | **3.240 kB** | |

**−70 % con `VACUUM FULL`; solo −19 % sin él.** Payload medido: **553 B de
media**, 7,77 actores por ficha, máximo 20 — coherente con los 642 B / 9,31 / 30
de producción y muy por debajo del umbral de TOAST.

Reparto de roles antes de migrar: ACTOR 12.581 (84,7 %), CREATOR 1.136,
DIRECTOR 633, AUTHOR 498, WRITER 8, SOURCE_AUTHOR 5.

---

## 8. ⚠️ Lo que **no** he podido verificar — para la QA del leader

Yo no tengo las credenciales de Neon. Tres cosas quedan pendientes contra
producción, y la primera es un riesgo de despliegue, no una curiosidad:

### 8.1 🔴 La migración probablemente **no cabe** en producción tal cual

Todo corre en una transacción, así que nada se devuelve al filesystem hasta el
commit. Mientras corre, la base sostiene el `credits` viejo (136 MB) **más**
`item_cast` (~34 MB) **más** el `credits` nuevo (~25-30 MB): un **pico de ~60-70
MB por encima del tamaño de partida**. Producción arrancó esta feature en **484
MB de 512** — unos 28 MB de margen. **Falta espacio.**

No es algo que la migración pueda resolverse a sí misma (bajar el pico exigiría
partirla en varias transacciones, que es justo lo que el brief prohíbe). Es una
decisión de despliegue. La palanca más barata que veo: **`catalog_search` son
105 MB de dato derivado** — dropear la vista materializada, desplegar, y
recrearla + `REFRESH` después. Está documentado en el docstring de la migración
bajo «Disk headroom this needs — read before deploying». **Conviene decidirlo
antes de mergear a `main`, porque Render aplica la migración al desplegar.**

### 8.2 🟠 Hace falta `VACUUM FULL people` y `VACUUM FULL external_ids` después

`DELETE` marca tuplas muertas; **no encoge el archivo**. Lo medí: sin el vacuum
el ahorro local baja de −70 % a −19 %. `credits` no lo necesita (se recrea, su
archivo es nuevo). `VACUUM FULL` no puede correr dentro de una transacción, así
que no puede vivir en la migración.

Ojo al orden: tras el swap de `credits` habrá ~100 MB libres, suficiente para
que el `VACUUM FULL` de `people` (56 MB) y luego el de `external_ids` (74 MB)
quepan de uno en uno.

### 8.3 El ahorro real y la proyección (criterios 10 y 11)

Los números de «antes» son los de `progress/measure_89.md` §1. Los de «después»
hay que medirlos contra Neon con la misma query, tras el `VACUUM FULL`. La
proyección de que el catálogo completo cabe (§7 del informe: A+B → ~444 MB,
~68 MB de margen) es **de ese informe, no mía**; yo no he podido contrastarla.
Y el aviso de su §10 sigue en pie: **`catalog_search` es la siguiente pared** y
ese margen depende de que su proyección a ~146 MB se cumpla.

### 8.4 Otras cosas que no verifiqué

- **`apps/web`**: no lo he tocado (criterio 13) y no he corrido `pnpm typecheck`.
  La forma de `CreditOut` no cambia, así que no toca regenerar `packages/api-client`.
  Lo que sí cambia de valor es `profile_url` en las entradas de reparto (§4.2) —
  el componente no lo lee, pero conviene mirarlo en la QA visual.
- **La colección `bruno/`** la actualicé pero no la ejecuté contra un servidor.
- **La DB de desarrollo local ya está migrada** (`alembic upgrade head` +
  `VACUUM FULL`), así que la QA manual con `curl` puede hacerse directamente.
  Producción no la he tocado.

---

## 9. Output de `bash init.sh`

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
[OK]    backend_feature_list.json válido (89 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
314 files already formatted
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
........................................................................ [ 83%]
........................................................................ [ 88%]
........................................................................ [ 93%]
........................................................................ [ 98%]
..................                                                       [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x...> with identity key
  (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None)
  conflicts with persistent instance <Credit at 0x...>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1458 passed, 1 warning in 33.28s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

El único warning es del propio test que añade a propósito una fila con la clave
primaria duplicada: es el ORM detectando el conflicto antes que Postgres, que es
justo lo que ese test demuestra. Ya existía con la constraint anterior.

---

## 10. Cierres de la review (aplicados después del veredicto APPROVED)

Seis puntos de `progress/review_89.md` §2 y §4. Ninguno es un rediseño; los seis
son higiene y documentación. El leader midió además los tres descartes
silenciosos contra producción (`progress/qa_89.md` §4) y **los tres son cero**:
credits con `item_type` fuera de `('MOVIE','SERIES','BOOK','GAME')` → 0 (solo
existen MOVIE 684.413 y BOOK 26.360); roles fuera del vocabulario → 0; actores
con nombre vacío → 0. Es decir: **ninguno de estos cambios mitiga un riesgo
vivo**. Se aplican igual porque cerrar un hueco de una línea antes de una
migración irreversible es barato, y porque una cifra equivocada en un docstring
envenena a quien la lea dentro de seis meses.

| # | Qué | Dónde |
|---|---|---|
| 1 | **Cifra del pico corregida**: de «~60-70 MB» a **~80-90 MB sobre los 484 de partida**, con la tabla del desglose | `alembic/versions/0037_*.py`, §«Disk headroom this needs» |
| 2 | **`_assert_known_vocabulary` valida `item_type` contra `_CREDIT_ITEM_TYPES`**, no contra `ITEM_TYPE_CODES` | `alembic/versions/0037_*.py` |
| 3 | **Código muerto borrado**: `cast_payload_json`, `item_type_from_code`, `credit_role_from_code` (y de `__all__`); `GRAPH_ROLES` conservado pero re-etiquetado | `backlogg/shared/credits.py`, `backlogg/shared/codes.py` |
| 4 | **Descarte de `p.name <> ''` documentado** | `alembic/versions/0037_*.py`, comentario de `_BACKFILL_ITEM_CAST` |
| 5 | **El slug vacío del issue #18** dicho explícitamente | `docs/api.md` + docstring de `cast_payload_to_credits` |
| 6 | **Test de migración fijado a `"0037"`** en vez de `"head"` | `tests/test_credits_cast_graph_split.py` |

### Detalle de los dos que no son puramente textuales

**(2) El hueco de vocabulario.** `ITEM_TYPE_CODES` incluye `PERSON`, que es un
tipo de `external_ids` y nunca algo a lo que apunte un credit. Un
`ACTOR`/`item_type='PERSON'` pasaba la guarda y luego **no entraba en ninguna de
las dos tablas** — `_BACKFILL_ITEM_CAST` lo filtra por `_CREDIT_ITEM_TYPES` y
`_COPY_GRAPH_CREDITS` solo se lleva los roles no-cast. Ahora la guarda usa el
mismo vocabulario que el filtro, así que «pasa la validación» e «acaba en algún
sitio» son la misma condición. El mensaje de error también cambió: ya no habla
solo de `codes.py`, dice qué se perdería y por qué.

Verificado a mano, no solo por inspección: sembré una base de scratch a 0036 con
un credit `('PERSON', 5, 1, 'ACTOR')` y corrí el upgrade.

```
RuntimeError: credits.item_type holds values this migration cannot map:
['PERSON']. Every row has to end up in either credits or item_cast, and these
would end up in neither. ...
```

`alembic_version` se quedó en `0036`: aborta antes de escribir nada, que es el
punto.

**(3) `GRAPH_ROLES`.** El reviewer tenía razón en que el comentario lo
presentaba como si algo se bifurcara sobre él. Nada lo hace: las tres rutas de
escritura se bifurcan sobre `CAST_ROLE`, del que es el complemento, precisamente
porque «¿esto es reparto?» es la pregunta que realmente se hacen y un
complemento no puede desincronizarse de sí mismo. El comentario ahora dice eso y
lo etiqueta como documentación ejecutable: la enumeración de qué sobrevive en
`credits`, en un sitio, junto a la constante que lo decide.

### Verificación

`bash init.sh` → **exit 0**, ruff check y format limpios, **1.458 tests**, mismo
único warning de siempre (el test que duplica la PK a propósito). Sin cambios en
`apps/web/`, sin commit, sin tocar `progress/current.md`.
