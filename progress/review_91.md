# Review — feature 91: search_expression_index

**Veredicto:** APPROVED

Con dos salvedades explícitas, ninguna bloqueante para el merge:

1. **Cuatro comentarios obsoletos en `tests/test_search.py`** que describen un
   paso de refresco que ya no existe (detalle abajo). Recomiendo corregirlos en
   el mismo commit — son exactamente el tipo de mentira silenciosa contra la que
   avisa el resto de la feature.
2. **El criterio de aceptación 9 no está completo y no puede estarlo todavía**:
   el «ANTES» está medido (`progress/measure_91.md`), el «DESPUÉS» exige el
   despliegue. La feature **no debería pasar a `done`** hasta registrar la
   medición post-despliegue, igual que se hizo con la 89 (`progress/deploy_89.md`).

Todo lo demás está verificado por mí, no leído del informe.

---

## Lo que verifiqué a mano en los cuatro puntos que se pidió apretar

### 1. `ts_rank` lee la columna almacenada — en las cuatro ramas ✅

No me fié del test (que solo cubre la rama `MOVIE`). Compilé la consulta
completa de cuatro ramas con `literal_binds` y conté:

```
ts_rank occurrences: 4
to_tsvector occurrences: 0
```

Las cuatro son literalmente `ts_rank(movies.search_vector, ...)`,
`ts_rank(series.search_vector, ...)`, `ts_rank(books.search_vector, ...)`,
`ts_rank(games.search_vector, ...)`. Y el `@@` del `WHERE` también va contra la
columna almacenada en las cuatro, que es lo que permite al GIN responderlo.

Es correcto **por construcción**, no por copia: `_row_branch`
(`backlogg/search/repository.py:240`) es una sola función parametrizada por
`_SearchSource`, así que no hay cuatro sitios que puedan divergir. El riesgo que
señalabas —una rama que recompute y ningún test que lo note— está estructuralmente
cerrado, no solo asertado.

### 2. Mapeo de fechas por tipo ✅

En el SQL compilado, rama a rama:

| Rama | Columna filtrada y proyectada como `release_date` |
|---|---|
| `MOVIE` | `movies.release_date` |
| `SERIES` | `series.first_air_date` |
| `BOOK` | `books.first_publish_date` |
| `GAME` | `games.release_date` |

Coincide con la vista retirada (`alembic/versions/0031_...py`, `_create_view`).
La columna se usa **tanto** en el `WHERE` (`date_from`/`date_to`) **como** en el
`SELECT`, que son los dos sitios donde el fallo sería silencioso.

Cobertura por tipo: `test_date_range_filters_each_type_on_its_own_date_column`
está parametrizado con los cuatro tipos y un rango de un solo día que aísla a
uno, más `test_release_date_reported_per_type_comes_from_the_right_column` que
fija la proyección. Un `first_air_date` cambiado por `release_date` en la rama de
series haría fallar ambos.

### 3. Una sola expresión de tsvector ✅

- `SEARCH_VECTOR_SQL` (`backlogg/shared/search_vector.py:58`) es la única
  definición; la importan los cuatro modelos ORM y la migración `0038`
  (`alembic/versions/0038_search_expression_index.py:135`).
- Comprobado que el DDL que genera cada modelo es **byte a byte el mismo** en
  las cuatro tablas, y que el texto coincide con `_SEARCH_VECTOR_EXPR` de la
  migración `0031` — es decir, la expresión que hoy está en producción. La
  búsqueda no cambia de semántica al migrar.
- Comprobado contra la DB de test real (creada por `alembic upgrade head`):
  las cuatro tablas tienen `search_vector` con `is_generated = ALWAYS`.
- El test `test_the_four_expressions_are_byte_identical` vigila desde
  `pg_attrdef`, que es el lado correcto: detectaría una divergencia introducida
  por una migración futura, no solo por el ORM.

Un matiz que me gusta: el `downgrade` reconstruye la vista **interpolando la
misma constante**, así que la vista recreada no puede divergir de la original.

### 4. `REFRESH MATERIALIZED VIEW` — cero llamadas ejecutables ✅

Confirmado el cuarto sitio que encontró el implementer:
`scripts/seed_openlibrary_books.py:369` (el `refresh_catalog_search` tras
`writer.flush()` y su import en la línea 94). Estaba ahí y ya no está.

**No hay un quinto.** Grep sobre todo el repo (excluyendo `.git`,
`alembic/versions` y `progress/`) de `REFRESH MATERIALIZED`,
`refresh_catalog_search`, `catalog_search` y `CatalogSearchEntry`: lo único que
queda en `backlogg/`, `scripts/`, `.github/` y `bruno/` son **docstrings y
comentarios** que explican por qué ya no existe. En `tests/` la única sentencia
real viva es la de `test_search_expression_index.py:671`, que es deliberada:
ejecuta un `REFRESH ... CONCURRENTLY` contra la vista **recreada por el
downgrade** para demostrar que `uq_catalog_search_type_id` volvió. Correcto.

Verificado también que `backlogg/search/models.py` (borrado) no lo importa nadie.

### 5. Orden y paginación — el `item_type` después de `id` ✅ y además mejora

El razonamiento del implementer es correcto y lo sostengo formalmente: **añadir
una clave al final de un `ORDER BY` no puede reordenar ningún par que difiera en
alguna clave anterior**. El comparador nunca llega a `item_type` salvo cuando
`(rating_external, rank, id)` empatan los tres, y ese caso era exactamente el que
antes quedaba a merced del plan de ejecución. Es un refinamiento estricto.

Y va un paso más allá de lo que dice el informe: `(id, item_type)` **sí** es
único sobre la unión (el `id` es único por tabla y el `item_type` identifica la
tabla), así que la cadena completa es ahora un **orden total**. Bajo la vista,
`(rating, rank, id)` no lo era —película 7 y libro 7 empatados podían alternar
entre páginas—, así que esto no solo conserva la garantía del issue #14: **cierra
un agujero que la vista tenía**. `test_pagination_is_stable_across_types_that_share_an_id`
lo fija con dos ítems de tipo distinto, mismo título y mismo rating.

---

## Sobre el WAL y `neon.max_cluster_size`

**Estoy de acuerdo contigo, y no veo fallo en el razonamiento.** Lo refuerzo con
dos cosas:

1. **La aritmética del contrafactual cierra.** Según `progress/deploy_89.md`, la
   `0037` partió de 400 MB de cluster con un pico estimado de ~485 MB de 512, es
   decir **~27 MB de holgura**. Si los 100+ MB de WAL de reescribir `credits`
   (710.772 filas) más los dos `DELETE` de 175.306 filas hubiesen contado contra
   el techo, no habría hecho falta afinar: habría fallado por un factor de ~4.
   Terminó con éxito. La hipótesis «el WAL cuenta» queda refutada por los datos.
2. **El mecanismo coincide.** El error que ha dado producción en este proyecto es
   `could not extend file because project size limit has been exceeded`: se
   dispara al **extender un fichero de relación**, y lo que se compara es el
   tamaño lógico (suma de relaciones, lo que ve `pg_database_size`). El flujo de
   WAL no extiende relaciones. Por eso el análisis del §5 del implementer sí es
   el correcto: lo que cuenta es que el heap viejo y el nuevo coexisten **hasta
   el `COMMIT`**, no cuánto WAL se genere por el camino.

Matiz, no objeción: lo que el WAL sí afecta es el almacenamiento facturado y la
retención de historia de Neon, que no es el techo de 512 MB. El riesgo abierto
del §7.2 del informe queda, en mi opinión, **cerrado**; el que sigue vivo es el
§7.1 (el tamaño real de las cuatro tablas, que es una deducción por resta), y ese
se resuelve con una consulta antes de desplegar.

---

## Migración 0038

- `upgrade` y `downgrade` **reales**, ambos ejercitados contra una base scratch
  con una fila de cada tipo (`test_migration_0038_upgrades_and_downgrades_with_data`),
  con `_alembic("upgrade", "0038")` fijado a la revisión y no a `head` — correcto,
  el día que aterrice la `0039` este test seguirá probando lo que dice probar.
- El `downgrade` recrea la vista **y sus tres índices**, incluido
  `uq_catalog_search_type_id`, y el test lo demuestra ejecutando un `REFRESH
  ... CONCURRENTLY` real (que sin ese índice único se negaría a correr).
- El test cubre lo que de verdad importa del despliegue: el backfill del vector
  en filas preexistentes (el caso de los 85.530 ítems de producción), una fila
  escrita *después* sin paso intermedio, la normalización del issue #13 viajando
  con la expresión, y que la columna generada **no se puede escribir a mano** —
  que es lo que convierte «no hay nada que refrescar» en garantía.
- `DROP MATERIALIZED VIEW IF EXISTS` al abrir: coherente con el runbook, que
  pide dropear a mano y commiteado antes de desplegar.
- C7 respetado: no recrea tablas.

---

## Checkpoints

- C1: [x] — `bash init.sh` ejecutado por mí, **exit code 0** (output completo abajo).
- C2: [x] — ningún `print()` en el código nuevo.
- C3: [x] — ningún TODO/FIXME nuevo.
- C4: [x] — `ruff check` y `ruff format` pasan.
- C5: [x] — **1.482 tests pasan** (eran 1.458; +24). El único warning
  (`SAWarning` en `test_credit_primary_key_constraint`) es preexistente de la 89.
- C6: [x] — `Mapped[...]` / `mapped_column` en los cuatro modelos, `Computed(..., persisted=True)`.
- C7: [x] — la `0038` no recrea tablas anteriores.
- C8: [x] — `upgrade()` y `downgrade()` implementados y probados con datos.
- C9: [x] — N/A estricto (no hay endpoints nuevos); `search/routes.py` sin tocar y sigue siendo `async` con `Depends`.
- C10: [x] — contrato de respuesta sin cambios, sigue en Pydantic v2.
- C11: [x] — sin URLs nuevas.
- C12: [x] — N/A (el fan-out externo de `/v1/search` no cambia).
- C13: [x] — 24 tests nuevos en `tests/test_search_expression_index.py`.
- C14: [x] — las fechas siguen llegando convertidas desde los adaptadores; esta feature no toca ese camino, solo elige la columna por tipo.
- C15: [x] — los fixtures nuevos usan slugs propios con prefijo `f91-`, sin colisión con el resto de la suite.
- C16-C19: [x] — N/A / sin regresión: el nocturno pierde el refresco y sus tests siguen verdes (`tests/test_admin_sync.py`, `test_sync_slice_cursor.py`, `test_sync_seed_limits.py`).
- C20: [x] — `routes.py` intacto.
- C21: [x] — `search/service.py` solo pierde la llamada al refresco; no entra ninguna query.
- C22: [x] — el repositorio devuelve dicts, el servicio los pasa a Pydantic. Sin ORM en la respuesta.

Ningún checkpoint en `[ ]`.

---

## Criterios de aceptación de la feature 91

| # | Criterio | Estado |
|---|---|---|
| 1 | Medir si `ts_rank` aporta, decidir A1/A2 con ese número | ✅ `progress/measure_91.md`, A2 con 35-75 % de reordenación |
| 2 | La vista deja de existir y con ella todo `REFRESH` | ✅ verificado con grep exhaustivo |
| 3 | `UNION ALL` conservando filtros de tipo, fecha y rating | ✅ y el tipo **poda ramas**, no filtra después |
| 4 | Contrato de `GET /v1/search` sin cambios | ✅ mismos campos, mismo orden, misma paginación con `total` |
| 5 | Estabilidad de paginación (issue #14) | ✅ y reforzada a orden total |
| 6 | Ítem recién ingerido buscable sin refresco, con test | ✅ parametrizado por los cuatro tipos |
| 7 | `search/models.py` y el resto dejan de referenciar la vista | ✅ archivo borrado, cero importadores |
| 8 | Migración con `upgrade`/`downgrade` probados; el downgrade recrea la vista y sus tres índices | ✅ |
| 9 | Tamaño medido **antes y después** contra producción + proyección | ⚠️ **parcial**: antes medido, proyección actualizada en `docs/seeding-plan.md`; **el después exige desplegar** |
| 10 | El nocturno deja de refrescar y no se rompe | ✅ `scheduler/jobs.py` limpio, suite de sync verde |
| 11 | `bruno/` sincronizado si cambia algún contrato | ✅ el contrato no cambia; los 10 `.bru` de `bruno/Search/` siguen siendo válidos y no hay huérfanos |
| 12 | `docs/schema.md`, `docs/api.md`, `docs/operations.md` + issue #28 cerrado | ✅ los tres reescritos donde tocaba; issue #28 → `resolved` con `solution`/`verification` |
| 13 | `bash init.sh` en verde | ✅ exit 0, verificado por mí |

---

## Hallazgos por gravedad

### Bloqueantes

Ninguno.

### Menores — corregir antes del commit, no bloquean el merge

1. **Cuatro comentarios/docstrings obsoletos en `tests/test_search.py`** que
   describen un `REFRESH` que ya no se ejecuta. La línea que refrescaban se
   borró; el texto se quedó:
   - línea 141: `"""Seed one item of each type, then refresh the materialized view."""`
   - línea 147: `# Refresh the materialized view so the inserted rows are visible to search`
   - línea 663: `# The other ingests and refresh must have executed despite the movies failure`
   - línea 727: `"""Seed movies with punctuated titles, then refresh the materialized view."""`

   Es cosmético, pero esta feature entera va de que el código no mienta en
   silencio, y son los cuatro últimos sitios donde lo hace.

2. **Divergencia ORM ↔ DB en la nullabilidad de `search_vector`.** Los cuatro
   modelos declaran `nullable=False`; la migración `0038` añade la columna sin
   `NOT NULL`. Comprobado contra la DB de test:

   ```
   table_name | is_nullable | is_generated
   books      | YES         | ALWAYS
   games      | YES         | ALWAYS
   movies     | YES         | ALWAYS
   series     | YES         | ALWAYS
   ```

   **Inofensivo en runtime**: `title` es `NOT NULL` en las cuatro tablas y
   `overview` va dentro de un `COALESCE`, así que la expresión nunca puede dar
   `NULL`; y nadie inserta esa columna. Pero es deriva real de metadatos: un
   `alembic autogenerate` futuro emitiría un `alter_column(nullable=False)`
   espurio. Se arregla eligiendo un lado (o `nullable=True` en el ORM, o
   `NOT NULL` en una migración futura — **no** tocando la `0038`, que va camino
   de producción).

### Operativo — no es código, es el runbook

3. **El runbook no dice cómo recuperar la búsqueda si el paso 3 aborta.** Si se
   ejecuta el `DROP MATERIALIZED VIEW` manual (paso 2) y el despliegue falla, la
   base se queda en `0037` **sin vista**: `alembic downgrade 0037` no sirve
   (ya se está en 0037) y `/v1/search` queda en 500 sin salida documentada. La
   recuperación existe —recrear la vista con el DDL de la `0031`, o ir al plan B
   de aplicar los `ALTER` a mano— pero conviene que esté escrita en
   `docs/operations.md` junto al resto, porque es el momento en que nadie quiere
   ponerse a deducirla.

4. **Aviso menor de ventana**: entre el paso 2 y el final del paso 3, el
   nocturno de GitHub Actions (código viejo aún en Render) intentaría refrescar
   una vista inexistente. No rompe nada —`scheduler/jobs.py` envolvía esa llamada
   en `try/except` con `logger.exception`—, pero si el despliegue se hace de
   noche conviene saberlo.

### Confirmaciones que pedías y que no son hallazgos

- El cuarto sitio (`scripts/seed_openlibrary_books.py`) **existía** y está
  eliminado. **No hay un quinto.**
- La eliminación del `commit()` que vivía dentro de `refresh_catalog_search` es
  segura: cada `_ingest_*` del fan-out abre su propia sesión con `db.begin()` y
  commitea por su cuenta, y el motor va en `READ COMMITTED` (sin
  `isolation_level` explícito en `backlogg/core/database.py:25`), así que la
  re-consulta posterior toma un snapshot nuevo y ve esas filas.
- `Computed(...)` asigna `server_default`, luego `_required_columns` y
  `_defaulted_columns` de `backlogg/shared/bulk_load.py` excluyen
  `search_vector`: verificado ejecutando el código, no leyéndolo. La ruta de
  lotes no se rompe.

---

## Output de `bash init.sh` (ejecutado por el reviewer)

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
[OK]    backend_feature_list.json válido (90 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
316 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [  4%]
........................................................................ [  9%]
........................................................................ [ 14%]
........................................................................ [ 19%]
........................................................................ [ 24%]
........................................................................ [ 29%]
........................................................................ [ 34%]
........................................................................ [ 38%]
........................................................................ [ 43%]
........................................................................ [ 48%]
........................................................................ [ 53%]
........................................................................ [ 58%]
........................................................................ [ 63%]
........................................................................ [ 68%]
........................................................................ [ 72%]
........................................................................ [ 77%]
........................................................................ [ 82%]
........................................................................ [ 87%]
........................................................................ [ 92%]
........................................................................ [ 97%]
..........................................                               [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x7ff9602c85d0> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7ff9604668d0>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1482 passed, 1 warning in 36.69s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.

[exited with code 0]
```
