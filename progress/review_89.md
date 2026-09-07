# Review — feature 89: `credits_people_storage_redesign`

**Veredicto: APPROVED**

Rama `feat/credits_people_storage_redesign` (trabajo sin commitear, revisado
sobre el working tree). `bash init.sh` ejecutado por mí: **exit 0, 1.458 tests
en verde**. Ningún hallazgo bloqueante.

He apretado donde el brief pedía: la migración, la purga, el `TypeDecorator`,
la lectura fusionada, `get_authorship_works`, los tests modificados, `bruno/` y
`docs/schema.md`. Detalle abajo. Lo que queda pendiente son **gates de
despliegue**, no defectos de implementación.

---

## Checkpoints

- C1  [x] `bash init.sh` exit 0 — verificado por mí, no por el informe.
- C2  [x] Sin `print()` en el código nuevo.
- C3  [x] Sin TODO/FIXME/XXX en el código nuevo.
- C4  [x] `ruff check` + `ruff format --check` en verde.
- C5  [x] 1.458 passed, 1 warning (el SAWarning es del test que provoca el
      conflicto de PK a propósito; ya se conocía).
- C6  [x] SQLAlchemy 2.0: `Mapped`/`mapped_column`, `select()`, `scalar_one_or_none()`.
      `ItemCast` y el `Credit` estrechado siguen el mismo estilo.
- C7  [x] **con matiz, explicado abajo (§3.1).** `0037` no recrea una tabla ya
      existente por descuido: crea `credits_new`, copia, hace swap y borra la
      vieja. El rebuild está justificado con números en el docstring y era el
      camino aprobado en `measure_89.md`.
- C8  [x] `upgrade()` y `downgrade()` implementados **y probados con datos**
      (`test_migration_0037_upgrades_and_downgrades_with_data`, base de scratch
      `backlogg_migration_0037`, 0036 → 0037 → 0036).
- C9  [x] No se toca ningún route handler; los existentes siguen `async` +
      `Depends(get_db)`.
- C10 [x] `CreditOut` / `PersonOut` siguen siendo Pydantic v2 y no cambian de forma.
- C11 [x] No cambia ninguna URL; `/people/{slug}` sigue por slug.
- C12 [x] `GET /people/{slug}` sigue devolviendo 404, ahora también para el
      actor de solo-reparto — con test HTTP y request en `bruno/`.
- C13 [x] No hay endpoints nuevos. Los dos cambios de comportamiento tienen test
      extremo a extremo por HTTP (`test_a_person_who_directs_and_acts_...`,
      `test_a_cast_only_person_is_a_404`).
- C14 [x] No entran fechas externas nuevas. `created_at` lo pone el server
      default en la migración y la ruta `sqltypes.DateTime` de `_coerce` sigue
      exigiendo `datetime` (el nuevo bloque de `TypeDecorator` se inserta antes
      y delega en `impl_instance`, sin saltarse esa comprobación).
- C15 [x] Los datos de test nuevos usan ids/slugs únicos (`-89`, `8400112`,
      `99002`, `gap-cast-tmdb-1/2`).
- C16 [x] n/a — el fallback on-demand sigue persistiendo antes de devolver;
      ahora en dos tablas.
- C17 [x] n/a — sin cambios.
- C18 [x] Idempotencia mantenida: `upsert_credit` pasa a
      `ON CONFLICT DO NOTHING` sobre `credits_pkey` (ya no queda nada que
      actualizar) y `upsert_item_cast` reescribe el array entero.
      `test_a_graph_credit_survives_a_person_rename` y
      `test_upsert_item_cast_replaces_the_array_wholesale` lo fijan.
- C19 [x] n/a.
- C20 [x] Sin lógica en `routes.py`.
- C21 [x] **con matiz (§3.2).** `movies/service.py` y `series/service.py` llaman
      a `upsert_item_cast` de `shared/credits.py`; no escriben queries. Es el
      mismo patrón que ya tenían con `get_credits_for_item` desde antes de la 89.
- C22 [x] Se sigue devolviendo Pydantic, nunca ORM.

**Ningún checkpoint en `[ ]`.**

---

## 1. Lo que he verificado a fondo (y está bien)

### 1.1 La purga de `people` / `external_ids` — el riesgo nº1

`_COLLECT_CAST_ONLY_PEOPLE` (0037:248-257) selecciona
`DISTINCT person_id WHERE role = 'ACTOR' AND NOT EXISTS (otro credit del mismo
person_id con role <> 'ACTOR')`. **La condición es exacta**: quien dirige *y*
actúa tiene una fila DIRECTOR, luego el `NOT EXISTS` lo excluye y sobrevive con
todos sus credits de grafo. Cero falsos positivos posibles. Los 9.251 directores
que además actúan están a salvo, y el test lo fija con el caso Eastwood.

Tres cosas más que verifiqué en ese camino y que también están bien:

- La temp table se calcula **antes** de `DROP TABLE credits` (línea 275 vs 298),
  o sea contra la tabla vieja completa. Correcto.
- El backfill de `item_cast` corre **antes** de la purga (272 vs 309-322): los
  nombres se copian mientras las filas de `people` todavía existen. Si el orden
  estuviera invertido se perdería el reparto entero; no lo está.
- El `ON DELETE CASCADE` del `DELETE FROM people` recorre la tabla **nueva**
  (solo grafo), y por construcción los borrados no tienen ni una fila allí. No
  hay pérdida colateral de credits de grafo por cascada.
- El `DELETE FROM external_ids` filtra por `item_type = 'PERSON'` en texto —
  correcto, `external_ids` **no** se migró a `smallint`. Las 13.717 de Open
  Library (autores) no entran en el conjunto porque tienen credits AUTHOR.

### 1.2 Cobertura del recorrido por ventanas

`_walk_windows` (0037:187-199) es correcto y **completo**, incluidos huecos y
bordes: las ventanas son `[lo, lo+W)` contiguas y sin solape, la primera arranca
en `MIN` y el bucle sigue mientras `lo <= MAX`, de modo que la última ventana
siempre contiene `MAX` (si no lo contuviera, el bucle habría dado otra vuelta).
Los huecos de `item_id` no rompen nada: una ventana vacía simplemente no escribe.
Fuente vacía → `MIN is None` → return sin trabajo. También verifiqué que los
`MIN/MAX` se toman del superconjunto correcto en cada caso (`credits.item_id`
para las dos copias, `_f89_cast_only_people.id` para las dos purgas,
`item_cast.item_id` para el downgrade).

### 1.3 El swap de tabla, constraints e índices

- `credits_new_pkey` → `credits_pkey` y `credits_new_person_id_fkey` →
  `credits_person_id_fkey`: los nombres por defecto de Postgres son los
  correctos porque `Base` **no** declara `naming_convention` (verificado en
  `backlogg/core/database.py`), así que `create_all` en tests y Alembic en
  producción convergen al mismo nombre. Eso es lo que hace válido el
  `on_conflict_do_nothing(constraint="credits_pkey")` de
  `people/repository.py:239`.
- Los tres índices se recrean con sus nombres originales; los viejos se fueron
  con el `DROP TABLE`. No queda ningún nombre huérfano ni duplicado.
- Verifiqué que **nada más depende de `credits`**: `catalog_search` (0031) solo
  lee `movies`/`series`/`books`/`games`, y la única FK contra `people` es la de
  `credits`. `DROP TABLE credits` sin `CASCADE` no puede fallar por dependencias.
- El `downgrade` reconstruye `credits_old` **idéntica a 0001**: mismo orden de
  columnas, mismos tipos, `BIGSERIAL`, `uq_credit` y los tres índices; incluso
  renombra `credits_old_id_seq` → `credits_id_seq`. Comparado línea a línea
  contra `0001_shared_models.py:100-121`.
- El docstring del `downgrade` promete exactamente lo que el código hace, y el
  test lo comprueba en las dos direcciones, incluida **la asimetría** (Eastwood
  vuelve desde `item_cast`, Bee Vang y Ahney Her no). Cumple la regla de
  `docs/conventions.md` sobre downgrades con pérdida.

### 1.4 `codes.py` y los dos `TypeDecorator`

- El mapeo es **total y biyectivo** en los dos sentidos (5 tipos, 6 roles,
  códigos distintos, diccionarios inversos derivados del directo — no puede
  desincronizarse).
- Un valor desconocido **lanza**, no se coerce ni se descarta: `ValueError` en
  `process_bind_param`, `TypeError` si no es `str`. Test:
  `test_credit_rejects_an_unknown_role` (espera `StatementError` con
  "unknown credit role").
- **Caminos de escritura que esquivan el `TypeDecorator`** — los busqué todos:
  - `bulk_load.py` (COPY): cubierto, `_coerce` aplica a mano el bind processor
    (líneas 274-286) y convierte el rechazo en `RowRejected` por fila, no en
    aborto del lote. Correcto.
  - `scripts/bench_bulk_load.py`: su `DELETE` en SQL crudo usa
    `ITEM_TYPE_CODES["MOVIE"]` y borra también de `item_cast`. Correcto.
  - La migración: usa `CASE ... END` **sin `ELSE`**, así que un valor no
    listado da NULL y la columna `NOT NULL` aborta; y antes de escribir nada
    corre `_assert_known_vocabulary`, que falla con la lista de valores
    ofensivos. Nada se descarta en silencio.
  - No queda ningún otro SQL crudo contra `credits` en `backlogg/`, `scripts/`
    ni `tests/`: `tests/shared/test_bulk_load.py::_wipe` migró de `text(...)` a
    `delete(Credit)` por la ORM.
- Todas las comparaciones del código (`Credit.item_type == "BOOK"`,
  `Credit.role.in_(AUTHORSHIP_ROLES)`, etc.) siguen siendo strings. Verifiqué
  que no queda ninguna comparación cruzada `Credit.item_type` ↔ una columna de
  texto de otra tabla, que sería el fallo típico de este cambio.

### 1.5 La lectura fusionada y el contrato de `CreditOut`

`get_credits_for_item` devuelve la **misma forma y el mismo orden**: reparto
primero desde `item_cast` (ya ordenado en almacenamiento por `build_cast_payload`,
**sin recortar** — el test carga los 30 actores del peor caso medido y desordena
la entrada), crew después. El orden anterior lo producía
`ORDER BY billing_order ASC NULLS LAST` con solo las filas de reparto llevando
`billing_order`, así que la equivalencia se sostiene. El desempate del crew
`(created_at, person_id)` es además **más** determinista que antes (antes era
orden físico). Los tests de `movies`, `series` y `games` lo comprueban por HTTP.

### 1.6 `get_authorship_works` — el puente de la feature 74

Único cambio: `select(Credit.id)` → `select(Credit.person_id)` dentro de un
`EXISTS`, donde la proyección es irrelevante. El resto del statement —el gate
anti-traductor, el `union_all` por tipo, el `exclude`, el `order_by`— está
intacto. Verifiqué que `Credit.role.label("role")` conserva el
`CreditRoleCode` al atravesar el `subquery()`, de modo que `row.role` sigue
llegando como `"AUTHOR"`/`"SOURCE_AUTHOR"` y no como un número; el test nuevo
`test_authorship_bridge_survives_for_an_author_who_also_acts` lo fija
precisamente en el caso peligroso (alguien con credits de las dos clases).

**El bloque protegido de `tests/test_credits_source_author_role.py` (~475-547)
NO se ha tocado.** Verificado sobre los rangos de los hunks del diff: los tres
únicos hunks del archivo terminan en la línea 228. El helper `_persisted_roles`
sí cambió, pero solo para leer **también** `item_cast`: la pregunta del test
(«¿clasificó bien la ingesta este crew?») es la misma, con la respuesta buscada
en los dos sitios donde ahora vive.

### 1.7 Los tests modificados — ¿debilitan algo?

Revisé los 13 archivos uno a uno buscando aserciones tapadas. **No encontré
ninguna.** Al contrario, la mayoría se refuerzan:

- `test_person_dedup.py`: los tres tests invertidos no se limitan a borrar la
  aserción; afirman activamente que **no** hay fila en `people` ni en
  `external_ids` *y* que el nombre aterrizó en `item_cast` con la variante
  correcta por película. El dedup de crew, que sigue importando, queda intacto
  (`test_persist_movie_people_dedup_director_same_tmdb_id`).
- `tests/games/test_router.py`: `DEVELOPER` no está en el vocabulario y ninguna
  ruta de ingesta lo escribe (games no tienen person credits, `docs/schema.md`),
  así que cambiarlo a `DIRECTOR` es correcto. La aserción de orden que se pierde
  aquí está cubierta con más fuerza en
  `test_the_detail_page_gets_the_full_cast_in_billing_order`. El orden del crew
  sigue siendo determinista en ese test (mismo `created_at` transaccional,
  desempate por `person_id`).
- `tests/shared/test_bulk_load.py`: se añadió un crew a los lotes que solo
  tenían reparto — necesario, porque si no
  `test_people_of_a_batch_are_resolved_with_a_single_query` habría pasado a
  contar cero consultas y a no probar nada. El implementer lo vio y lo comenta.
  Además añade aserciones nuevas de que el reparto **no** crea `people` ni
  `external_ids`.
- `tests/shared/test_slug_non_latin_fallback.py`: el test de issue #18 conserva
  lo que le da sentido (el fallback de slug del creator) y comprueba que el
  nombre CJK del actor sobrevive intacto en `item_cast`.

### 1.8 `bruno/` y documentación

- `bruno/` sincronizado: no hay endpoints nuevos ni retirados, así que no hay
  `.bru` huérfanos; se añade
  `bruno/People/Get person by slug — cast-only actor (404).bru` y se documenta
  el caso 200-sin-ACTOR en el `.bru` existente. Los asserts de
  `bruno/Movies|Series/Get ... by slug.bru` sobre `billing_order` siguen siendo
  válidos (el campo sigue presente, puede ser `null`).
- `docs/schema.md` (criterio 12) cumple de sobra: modelo nuevo **con el
  razonamiento**, `item_cast` entera, las tres decisiones de la DDL con su
  número detrás, y la nota de las dos representaciones del vocabulario.
- `docs/api.md` documenta los dos comportamientos de `/people/{slug}` y la
  tabla de procedencia de `credits[]` — que era exactamente lo que
  `measure_89.md` §11.2 exigía «para que no se descubra en la QA».

### 1.9 La desviación no pedida (`get_credit_gaps`) está bien traída

El `LEFT JOIN item_cast` de `scheduler/repository.py:161-165` no es alcance
creep: sin él, una película con reparto pero sin crew de la allowlist tendría
cero filas en `credits` y volvería a la lista de trabajo **en cada run, para
siempre**, gastando una llamada a TMDB por noche. Tiene test
(`test_gap_query_treats_a_stored_cast_as_covered`). Aprobado.

---

## 2. Corrección al informe del implementer: el pico de disco está **subestimado**

El leader pidió que dijera si el análisis del §8.1 es incorrecto en cualquier
dirección. **Lo es, en la dirección optimista.** El docstring de la migración
(«a peak of ~60-70 MB above the starting size») contabiliza `credits` viejo +
`item_cast` + `credits` nuevo, pero **omite tres cosas que también viven dentro
de la misma transacción y por tanto en el mismo pico**:

1. **Los tres índices del `credits` nuevo** (`idx_credits_person`,
   `idx_credits_item`, `idx_credits_role`) se crean en las líneas 304-306,
   *después* del swap pero *antes* del commit, sobre ~193k filas: **~12-15 MB**
   que no están en la cuenta.
2. **La temp table `_f89_cast_only_people` más su índice**: 175.306 `bigint`
   → **~10 MB** (heap ~5,6 MB + btree ~4 MB). Se crea en la línea 275 y solo
   se suelta en la 323, es decir vive durante todo el tramo caro.
3. Las tuplas muertas y el WAL de los dos `DELETE` (≈250.000 filas entre
   `people` y `external_ids`), que tampoco se devuelven antes del commit.

Con eso el pico real está más cerca de **+80-90 MB sobre los 484 MB de
partida**, no de +60-70. **No cambia la conclusión** —seguía sin caber en los
28 MB de margen— pero sí cambia cuánto hay que liberar antes: si el plan es
dropear `catalog_search` (105 MB), el margen sigue siendo cómodo; si se pensaba
en una palanca más pequeña, con 70 MB no basta.

Esto **no bloquea el merge**; es un dato para la decisión de despliegue que el
leader está tomando en paralelo. Sí convendría corregir la cifra del docstring
de `0037` (líneas 50-55) para que no engañe a quien lo lea dentro de seis meses.

---

## 3. Los dos matices de checkpoint

### 3.1 C7 — la migración sí reconstruye `credits`

`0037` borra y recrea una tabla creada en `0001`. Literalmente eso es lo que C7
desaconseja, pero el checkpoint apunta a otra cosa (recrear por descuido una
tabla que ya existe, típicamente por no haber leído las migraciones previas).
Aquí es lo contrario: el rebuild es el mecanismo **elegido y justificado con
números** —`ALTER COLUMN TYPE` reescribe la tabla igual, `DROP COLUMN` no
libera espacio ni reordena el layout físico sin un `VACUUM FULL` que no cabe en
la transacción, y solo sobrevive el 27 % de las filas— y se hace por la vía
segura (`credits_new` + swap), no con un `create_table("credits")` a ciegas.
Lo marco `[x]` dejando constancia del matiz.

### 3.2 C21 — `service.py` y `upsert_item_cast`

`movies/service.py:174` y `series/service.py:176` llaman a `upsert_item_cast`,
que vive en `backlogg/shared/credits.py` y sí escribe SQLAlchemy. No es una
regresión de capas introducida por la 89: esos mismos servicios ya llamaban a
`get_credits_for_item` del mismo módulo antes de esta feature, y
`shared/credits.py` es una frontera compartida del mismo rango que
`shared/external_ids.py` o `shared/bulk_load.py` según `docs/architecture.md`.
Los servicios no construyen ninguna query. `[x]`.

---

## 4. Mejoras opcionales (NO bloquean, NO hace falta tocarlas ahora)

1. **Código muerto: cuatro símbolos públicos nuevos sin un solo consumidor.**
   - `backlogg/shared/credits.py:219` `cast_payload_json` — su docstring dice
     que lo necesitan «asyncpg's COPY, the migration», y **ninguno de los dos lo
     usa**: `item_cast` se escribe con `upsert_item_cast` (no COPY) y la
     migración construye el JSONB en SQL. Es un docstring que describe un uso
     que no existe, que es peor que la función.
   - `backlogg/shared/credits.py:51` `GRAPH_ROLES` — documentado como el
     complemento de `CAST_ROLE`, pero nadie se bifurca sobre él (todas las
     rutas comparan contra `CAST_ROLE`). Vale como documentación ejecutable;
     si se queda, mejor decirlo así en el comentario.
   - `backlogg/shared/codes.py:82,90` `item_type_from_code` /
     `credit_role_from_code` — exportados en `__all__` y sin llamadas: los
     `TypeDecorator` usan los dicts privados directamente.

2. **Vocabulario inconsistente entre las dos guardas de la migración.**
   `_assert_known_vocabulary` (0037:168) acepta `item_type = 'PERSON'` porque
   está en `ITEM_TYPE_CODES`, pero `_BACKFILL_ITEM_CAST` filtra
   `item_type IN ('MOVIE','SERIES','BOOK','GAME')` (`_CREDIT_ITEM_TYPES`). Un
   credit `ACTOR` con `item_type = 'PERSON'` pasaría la guarda y luego **no
   entraría en ninguna de las dos tablas**: se perdería en silencio. En la
   práctica es inalcanzable (ninguna ruta de escritura produce ese valor y la
   medición no lo encontró), por eso no bloquea; pero validar contra
   `_CREDIT_ITEM_TYPES` en vez de contra `ITEM_TYPE_CODES` cerraría el hueco
   con una línea y sin coste.

3. **`p.name <> ''` en el backfill descarta filas sin dejar rastro.**
   Coincide con la regla de `build_cast_payload` («entries with no name are
   dropped»), así que es coherente, pero es el único descarte silencioso de la
   migración y no aparece en el docstring. Una línea en el docstring de
   `_BACKFILL_ITEM_CAST` cerraría el tema.

4. **`person_slug` puede salir cadena vacía.** `cast_payload_to_credits` deriva
   el slug con `slugify(name)`, que para un nombre íntegramente CJK/cirílico/etc.
   devuelve `""` (issue #18). No rompe nada —`CreditOut.person_slug` no tiene
   `min_length`, no se persiste, no se usa para buscar, y la key de React de
   `ItemCredits` lleva el índice— pero `docs/api.md` dice «derivado del nombre,
   no resuelve» sin mencionar que además puede venir vacío. Merece media línea.

5. **`test_migration_0037_...` migra a `"head"`.** Cuando entre `0038` el test
   dejará de probar «0036 → 0037» para probar «0036 → lo que haya». Fijar
   `"0037"` lo haría estable.

6. **Proceso (menor):** el implementer reescribió `progress/current.md`, que
   según `CLAUDE.md` es del leader. El contenido crítico (por qué la 74 sigue
   en `in_progress`) sobrevive en las líneas 58-60, así que no hay pérdida —
   solo lo dejo anotado.

---

## 5. Criterios de aceptación

| # | Criterio | Estado |
|---|---|---|
| 1 | Distribución de `people` por nº de credits, medida contra producción | ✅ `measure_89.md` §2 |
| 2 | Decisión A/B tomada con esos números y por escrito | ✅ `measure_89.md` §6-§8 (descarta A sola y B con umbral **con cifras**) |
| 3 | `item_type` y `role` dejan de ser texto | ✅ `smallint` + `codes.py` |
| 4 | El `id` autoincremental desaparece, la clave natural es la identidad | ✅ PK `(item_id, person_id, item_type, role)` |
| 5 | El reparto deja de generar filas en `people` y `external_ids` | ✅ las tres rutas de escritura se bifurcan sobre `CAST_ROLE`; tests |
| 6 | Migración con backfill, upgrade y downgrade probados | ✅ con test contra una base con filas, en los dos sentidos |
| 7 | El puente de la 74 sigue funcionando, con test que lo fija | ✅ `test_authorship_bridge_survives_for_an_author_who_also_acts` + bloque protegido intacto |
| 8 | Contrato de detalle mantenido, o `api-client` + `pnpm typecheck` | ✅ la forma no cambia (`measure_89.md` §11.2 lo deja fuera del gate) |
| 9 | `bruno/` sincronizado | ✅ |
| 10 | Tamaño de las tres tablas ANTES y DESPUÉS, con cifras en el informe | 🟡 **antes** medido contra producción; **después** solo contra la DB de dev (`impl_89.md` §7). Falta la medida contra Neon — **QA del leader**, el implementer no tiene credenciales |
| 11 | Verificado que el catálogo completo cabe en 512 MB | 🟡 proyectado en `measure_89.md` §7 (~444 MB, ~68 MB de margen); no re-verificado tras implementar — **QA del leader** |
| 12 | `docs/schema.md` con el modelo nuevo **y el razonamiento** | ✅ |
| 13 | `bash init.sh` en verde | ✅ verificado por mí |

Los dos 🟡 son medidas contra producción, no trabajo de implementación
pendiente. El leader ya los tiene identificados como suyos.

---

## 6. Antes de mergear (gates de despliegue, no de código)

Render aplica la migración al desplegar `main`, así que esto va **antes** del
merge, no después:

1. **Hacer sitio.** El pico real es ~80-90 MB sobre 484 (§2 de esta review), no
   los 60-70 del docstring. Dropear `catalog_search` (105 MB de dato derivado)
   antes de desplegar y recrear + `REFRESH` después sigue siendo la palanca
   suficiente.
2. **`VACUUM FULL people` y luego `VACUUM FULL external_ids`** después del
   deploy, en ese orden. Sin ellos el ahorro medido cae de −70 % a −19 %: el
   `DELETE` marca tuplas muertas, no encoge el archivo.
3. **Medir las tres tablas contra Neon** después del vacuum (criterio 10) y
   revisar la proyección del criterio 11 — con `catalog_search` como la
   siguiente pared, tal y como avisa `measure_89.md` §10.

---

## 7. Output de `bash init.sh`

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
  <sys>:0: SAWarning: New instance <Credit at 0x7fec03b0dbd0> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7fec03b0ccd0>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1458 passed, 1 warning in 31.86s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(El único warning es el esperado: `test_credit_primary_key_constraint` inserta
a propósito una fila con la clave primaria duplicada y el ORM detecta el
conflicto antes que Postgres.)
