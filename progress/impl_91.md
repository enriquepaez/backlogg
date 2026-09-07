# Feature 91 — `search_expression_index` (informe de implementación)

Rama `feat/search_expression_index`. Sin commit. Diseño **A2**, ya decidido en
`progress/measure_91.md` — no se re-midió ni se reabrió.

---

## 1. Qué se ha hecho

`catalog_search` deja de existir. `movies`, `series`, `books` y `games` llevan
ahora su propia columna `search_vector tsvector GENERATED ALWAYS AS (...)
STORED` con un índice GIN cada una, y la búsqueda cross-type es un `UNION ALL`
sobre las cuatro. **No queda ninguna llamada a `REFRESH MATERIALIZED VIEW` en
el código** (solo en las migraciones antiguas, que son historia y no se tocan).

Los tres sitios que la instrucción señalaba, y uno más que apareció al buscar
consumidores:

| Sitio | Qué se hizo |
|---|---|
| `backlogg/search/repository.py::refresh_catalog_search` | Eliminado; el módulo entero se reescribió |
| `backlogg/scheduler/jobs.py::refresh_catalog_search` + 3 call sites | Eliminados |
| `backlogg/search/service.py:488` (`await self._repo.refresh_catalog_search()`) | Eliminado |
| `scripts/seed_openlibrary_books.py:370` | Eliminado (no estaba en la lista, lo encontró el grep de consumidores) |
| `backlogg/search/models.py::CatalogSearchEntry` | Archivo borrado — solo lo importaba `search/repository.py` |

## 2. La expresión vive en un solo sitio

`backlogg/shared/search_vector.py::SEARCH_VECTOR_SQL`. Lo leen los cuatro
modelos ORM **y** la migración `0038` (precedente: `0037` importa
`backlogg/shared/codes.py`). La constante lleva un aviso de congelación:
cambiarla reescribiría en silencio lo que significa una migración ya aplicada,
así que un cambio futuro exige migración nueva + copia congelada en la `0038`.

Hay un test que lo vigila desde el otro lado —
`test_the_four_expressions_are_byte_identical` consulta `pg_attrdef` y exige
que las cuatro tablas devuelvan **una sola** expresión distinta—, porque si
divergen la búsqueda empieza a comportarse distinto por tipo sin error alguno.

## 3. La query

`backlogg/search/repository.py`, reescrito. Conserva la firma, el contrato y el
orden. Cuatro decisiones que merecen nombre:

- **`ts_rank(model.search_vector, ...)`**, nunca `ts_rank(to_tsvector(...))`.
  Está asertado sobre el SQL compilado
  (`test_ts_rank_ranks_the_stored_column_and_never_recomputes_it`) porque
  ningún test de comportamiento distingue las dos formas: devuelven los mismos
  números y una recomputa el vector de cada fila candidata antes del `LIMIT`.
- **El `rank` se calcula dentro de cada rama**, no sobre la unión: lo que
  cruza la frontera del `UNION ALL` es un float, no ~0,7 KB de tsvector por
  fila candidata.
- **El `count` va sobre una unión que selecciona una constante**, no sobre las
  filas: contar no paga ni el `ts_rank` ni el payload.
- **`item_type` poda ramas**, no filtra después: una búsqueda con `type=book`
  no lee `movies`, `series` ni `games`.

Mapeo de fecha por tipo, replicado tal cual lo hacía la vista y fijado por
tests parametrizados uno a uno (un fallo aquí no daría error, solo dejaría de
filtrar):

| `item_type` | Tabla | Columna |
|---|---|---|
| `MOVIE` | `movies` | `release_date` |
| `SERIES` | `series` | `first_air_date` |
| `BOOK` | `books` | `first_publish_date` |
| `GAME` | `games` | `release_date` |

**Un cambio de orden, deliberado y declarado**: la cadena de desempate termina
en `item_type` *después* de `id`. `id` es único dentro de una tabla pero no
entre las cuatro, así que película 7 y libro 7 podían intercambiarse entre dos
peticiones de la misma página. Es un refinamiento estricto —solo resuelve
pares cuyo orden relativo era indefinido antes— y es lo que mantiene viva la
garantía del issue #14 ahora que el resultado es un `UNION ALL`. Está
documentado en el docstring y cubierto por
`test_pagination_is_stable_across_types_that_share_an_id`.

**El contrato de `GET /v1/search` no cambia**: mismos campos, mismos filtros,
misma paginación con `total`. `bruno/` no necesita cambios (verificado: los 10
`.bru` de `bruno/Search/` siguen siendo válidos y no hay huérfanos).

## 4. La columna en el ORM

Mapeada como `Computed(SEARCH_VECTOR_SQL, persisted=True)` y **`deferred=True`**.
El `deferred` no es cosmético: sin él, cada `select(Movie)` del código
arrastraría el tsvector.

Comprobado que no rompe la ruta de escritura por lotes: `Computed` asigna
`server_default`, y tanto `_required_columns` como `_defaulted_columns` de
`backlogg/shared/bulk_load.py` excluyen las columnas con `server_default`. Sin
eso, **cada fila de cada lote habría sido rechazada** por «missing required
columns: search_vector». `tests/shared/test_bulk_load.py` ahora incluye
`search_vector` en el snapshot de equivalencia entre la ruta por ítem y la ruta
por lotes (leyéndolo con un `select` explícito, porque tocar el atributo
diferido dispararía un lazy load que asyncio no puede servir).

---

## 5. El pico de disco de la migración, y el orden que lo hace caber

**Esto es el corazón de la feature y hay un detalle que es fácil entender al
revés.**

`alembic/env.py` envuelve todo el `upgrade` en **una** transacción. Un
`DROP MATERIALIZED VIEW` no devuelve los ficheros al sistema de archivos cuando
se ejecuta: Postgres los desenlaza en el `COMMIT`. Por tanto **dropear la vista
dentro de la migración no libera ni un byte para los `ALTER` que vienen
después**.

Y los `ALTER` cuestan: añadir una columna generada `STORED` **reescribe la
tabla** (heap nuevo + copias nuevas de todos sus índices), y las viejas siguen
en disco hasta el commit.

### Medido (no estimado) en la DB local

60.000 películas, `catalog_search` de 25 MB, base de 62 MB, mirando
`pg_database_size` desde dentro de la transacción abierta:

| Momento | `DROP` dentro del `BEGIN` | `DROP` commiteado antes |
|---|---|---|
| inicio | 62 MB | 62 MB |
| tras el `DROP` | **62 MB** | 36 MB |
| pico, a mitad del `ALTER` | **93 MB** | **67 MB** |
| tras el `COMMIT` | 40 MB | 40 MB |

La segunda fila es la prueba: dentro de la transacción el `DROP` no cambia
nada, y el pico acaba **26 MB más alto — exactamente el tamaño de la vista**.
Mismo estado final; solo cambia el techo que se toca.

### Proyectado a producción

Partiendo de los 385 MB de cluster, la vista de 137 MB y los ~90 MB de heap +
índices de las cuatro tablas de contenido (esos 90 MB son estimación, ver §7):

| Escenario | Pico | ¿Cabe en 512? |
|---|---|---|
| Vista dropeada **dentro** de la migración | 385 + 90 + 57 + 25 ≈ **557 MB** | **No** |
| Vista dropeada y **commiteada antes** | 248 + 90 + 57 + 25 ≈ **420 MB** | Sí, ~90 MB de margen |

(57 MB = el `search_vector` almacenado medido en producción; 25 MB = los cuatro
índices GIN.)

### El orden que propongo

1. `psql "$DATABASE_URL" -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;"`
   — medir primero; el techo es **por cluster**, no por base.
2. `psql "$DATABASE_URL" -c "DROP MATERIALIZED VIEW catalog_search;"` como
   sentencia **propia y commiteada, antes de desplegar**. A partir de aquí
   `/v1/search` devuelve 500 hasta que termine el paso 3, porque el código que
   sigue en Render consulta la vista; en free tier son minutos. La migración
   empieza con `DROP ... IF EXISTS` precisamente para que este paso manual la
   convierta en no-op en vez de en un conflicto.
3. Desplegar `main`. Render aplica la `0038`.
4. `ANALYZE movies, series, books, games;` — la reescritura deja ficheros
   nuevos (**no** hace falta `VACUUM FULL`, al contrario que en la feature 89)
   pero sin estadísticas para la columna nueva, y el planner las necesita para
   elegir el GIN.
5. Volver a medir: se esperan ~55 MB menos y `SELECT COUNT(*) FROM pg_matviews`
   a 0.

**Plan B si el paso 3 aun así no cabe**: aplicar los cuatro
`ALTER TABLE ... ADD COLUMN` + `CREATE INDEX ... USING GIN` a mano, **uno por
tabla, cada uno en su propia transacción** (la más pequeña primero, para que las
baratas aterricen aunque la última no), y luego `alembic stamp 0038`. Baja el
pico al de una sola reescritura en vez de cuatro. Está en el docstring de la
migración y en `docs/operations.md`.

El `downgrade` necesita el mismo margen en sentido inverso: reconstruye los
137 MB de la vista **mientras** las cuatro columnas generadas siguen existiendo.

---

## 6. Verificación

`bash init.sh` — **todo verde salvo un punto, que es de bookkeeping y no mío**
(ver §8): ruff check OK, ruff format OK, **1.482 tests pasan** (eran 1.458
antes; +24 nuevos). Output completo en §9.

### Migración probada de verdad

`test_migration_0038_upgrades_and_downgrades_with_data` (mismo patrón de base
scratch que usa la feature 89): crea una base nueva, migra a `0037`, mete una
fila de cada tipo, sube a `0038` y baja a `0037`. Comprueba, en ese orden:

- la vista desaparece;
- las cuatro filas preexistentes quedan con el vector **relleno** por la
  reescritura (es el caso de los 85.530 ítems ya en producción);
- la normalización de puntuación del issue #13 viajó con la expresión
  (`'spiderman'` encuentra `Spider-Man`);
- una fila insertada **después** de la migración obtiene su vector sin ningún
  paso intermedio;
- la columna generada **no se puede escribir a mano** — eso es lo que convierte
  «no hay nada que refrescar» en garantía y no en convención;
- el `downgrade` devuelve la vista **con sus tres índices**, y se ejecuta un
  `REFRESH MATERIALIZED VIEW CONCURRENTLY` real contra ella para demostrar que
  `uq_catalog_search_type_id` volvió (sin él, el refresh se niega a correr).

Además, fuera del test: comparé `pg_get_viewdef` de la vista recreada por el
`downgrade` contra la que deja `0037` en una base limpia. **Idénticas byte a
byte.**

### El índice GIN se usa de verdad

`EXPLAIN ANALYZE` sobre 60.000 filas locales con una consulta selectiva:

```
Bitmap Index Scan on idx_movies_search_vector
   Index Cond: (search_vector @@ '''42424'''::tsquery)
Sort Key: rating_external DESC NULLS LAST, (ts_rank(search_vector, ...)) DESC, id
```

El `ts_rank` del plan lee `search_vector`, no un `to_tsvector` recomputado.

### Tests nuevos — `tests/test_search_expression_index.py` (24)

Ítem recién ingerido buscable sin refresco (parametrizado por los cuatro
tipos); no queda ninguna vista materializada; las cuatro tablas tienen columna
generada + GIN; las cuatro expresiones son idénticas; filtros de fecha por tipo
(parametrizados uno a uno, más rango total y rango vacío); `release_date` de la
respuesta sale de la columna correcta por tipo; `ts_rank` sobre la columna
almacenada (sobre SQL compilado); sin `q` no hay columna de rank; poda por
`item_type`; `rating_external` como clave primaria de orden; banda de `NULL`
ordenada por `ts_rank`; paginación con `total` sin repeticiones; estabilidad
entre tipos que comparten `id`; filtro de rating cross-type; puntuación del
issue #13; y la migración arriba/abajo.

### Tests existentes tocados

Se retiraron ~90 líneas de mocks de `refresh_catalog_search` y sentencias
`REFRESH MATERIALIZED VIEW` repartidas por 14 archivos, más los
`assert_called_once()` que ya no tienen sujeto. Dos cambios que no son
mecánicos:

- `tests/test_openlibrary_dump_seeding.py`:
  `test_the_load_phase_refreshes_the_search_view` afirmaba justo lo contrario
  de lo que ahora es cierto («19 k filas invisibles hasta el refresco»).
  Sustituido por `test_seeded_books_are_searchable_with_no_refresh_step`, que
  siembra y busca sin nada en medio.
- `tests/shared/test_bulk_load.py`: `search_vector` entra en el snapshot de
  equivalencia entre las dos rutas de escritura, en vez de exentarse.

---

## 7. Qué NO he podido verificar

**No tengo credenciales de producción.** Todo lo medido aquí es contra la DB
local (`docker compose`, Postgres 16). Queda pendiente de medir contra Neon:

1. **El tamaño real de las cuatro tablas de contenido.** Los ~90 MB de heap +
   índices que uso en la proyección son una **deducción por resta**
   (385 − 22 sistema − 137 vista − 114 grafo de personas ≈ 112 MB, de los que
   descuento las tablas pequeñas). Si esa cifra se va a ~130 MB, el pico sube a
   ~460 MB y el margen se queda en ~50 MB: sigue cabiendo, pero conviene saberlo
   antes. Medida exacta:
   ```sql
   SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_catalog.pg_statio_user_tables
   WHERE relname IN ('movies','series','books','games');
   ```
2. **El pico real durante el despliegue.** Neon calcula
   `neon.max_cluster_size` sobre el tamaño lógico; **no he podido comprobar si
   el WAL de la reescritura (~150 MB para 90 MB de tablas) cuenta contra ese
   techo.** Si contase, la aritmética de §5 se queda corta y habría que ir al
   plan B (una tabla por transacción) directamente. Es el riesgo abierto más
   serio de esta feature.
3. **El ahorro real post-despliegue** (~55 MB esperados: 137 → ~82) y el nuevo
   tamaño de cluster (385 → ~330).
4. **Latencia de `/v1/search` en producción.** Localmente el `UNION ALL` de
   cuatro ramas con GIN responde en ~1,8 ms sobre 60 k filas sintéticas, pero
   ese corpus tiene títulos y overviews artificialmente cortos y no reproduce la
   distribución de `rating_external` que hace trabajar al `ORDER BY`.
5. **El comportamiento del `ALTER` sobre 85.530 filas reales** — cuánto tarda y
   si entra dentro del timeout de despliegue de Render. Localmente, 60.000 filas
   tardan segundos.

## 8. Un punto de `init.sh` que no puedo arreglar sin tocar otra feature

`init.sh` falla **solo** en la sección 3: «Hay 2 features en `in_progress`
(máximo 1)». La feature **74 está `in_progress` a propósito** —
`progress/current.md` lo explica: su criterio 9 depende de la siembra y se
cierra junto al issue #15— y yo marqué la 91 `in_progress` según el protocolo.

No lo toco: es estado de otra feature y es decisión del leader. Verificado que
es lo único que falla — poniendo la 74 en `blocked` (estado que `init.sh` acepta
y que describe literalmente su situación) la sección 3 pasa y `init.sh` termina
en verde. Las secciones 4, 5 y 6 ya están verdes tal cual.

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
[FAIL]  Hay 2 features en in_progress (máximo 1)

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
  <sys>:0: SAWarning: New instance <Credit at 0x7efd484d2fd0> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7efd4bca02d0>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1482 passed, 1 warning in 33.22s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[FAIL]  Entorno NO está listo. Resuelve los errores antes de avanzar.
```

(El `SAWarning` de `test_credit_primary_key_constraint` es preexistente, de la
feature 89; no lo introduce esta rama.)

---

## 10. Archivos

### Creados

| Archivo | Qué |
|---|---|
| `backlogg/shared/search_vector.py` | `SEARCH_VECTOR_SQL` y `SEARCH_TS_CONFIG`, la única definición del vector |
| `alembic/versions/0038_search_expression_index.py` | Retira la vista, añade las cuatro columnas generadas + GIN; `downgrade` reconstruye la vista y sus tres índices |
| `tests/test_search_expression_index.py` | 24 tests: sin refresco, mapeo de fechas, `ts_rank` sobre la columna, orden, paginación, migración arriba/abajo |

### Borrados

| Archivo | Por qué |
|---|---|
| `backlogg/search/models.py` | `CatalogSearchEntry` mapeaba la vista; solo lo usaba `search/repository.py` |

### Modificados

| Archivo | Cambio |
|---|---|
| `backlogg/search/repository.py` | Reescrito: `UNION ALL` sobre las cuatro tablas; fuera `refresh_catalog_search` |
| `backlogg/search/service.py` | Fuera la llamada al refresco tras el fan-out + docstring |
| `backlogg/search/schemas.py` | Docstring: ya no hay vista que citar |
| `backlogg/scheduler/jobs.py` | Fuera `refresh_catalog_search` y sus 3 call sites + docstring del módulo |
| `backlogg/movies/models.py`, `series/models.py`, `books/models.py`, `games/models.py` | Columna `search_vector` (`Computed`, `deferred`) + índice GIN en `__table_args__` |
| `backlogg/shared/codes.py` | Docstring: `catalog_search` ya no está en la lista de tablas con `item_type` textual |
| `scripts/seed_openlibrary_books.py` | Fuera el refresco tras la fase de carga |
| `tests/` (15 archivos) | Retirados mocks y sentencias de refresco; dos tests reescritos (ver §6) |
| `docs/schema.md` | Sección «Search» reescrita entera |
| `docs/api.md` | `GET /v1/search`: mapeo de fechas por tipo y «los resultados nunca están obsoletos» |
| `docs/operations.md` | Runbook del nocturno corregido + sección nueva «Despliegue de la migración 0038 — el orden importa» |
| `docs/seeding-plan.md` | Fila de dimensionado actualizada (1.959 → ~960 bytes/ítem) con nota de la feature |
| `issues_list.json` | Issue **#28 → `resolved`** |
| `backend_feature_list.json` | Feature 91 → `in_progress` |

### Issue #28

Cerrado con `solution` que dice explícitamente **por qué**: se cierra porque el
refresh desaparece, no porque quepa. Ni un refresh más pequeño ni uno no
concurrente: ninguno. Incluye por qué se descartó A1 (el índice de expresión
puro, que habría ahorrado ~112 MB en vez de ~55) con el número que lo decidió,
y `verification` con los comandos para comprobarlo en producción.

---

## 11. Correcciones tras la revisión (APPROVED, `progress/review_91.md`)

Cuatro puntos menores del informe del reviewer. Ninguno es rediseño; ninguno
cambia el contrato ni la query.

### 11.1 Comentarios obsoletos en `tests/test_search.py`

Tres sitios seguían describiendo un mecanismo retirado (peor que no tener
comentario):

| Antes | Ahora |
|---|---|
| `"""Seed one item of each type, then refresh the materialized view."""` (fixture `seeded_db`) | Explica que basta el `flush`, porque `search_vector` es columna generada |
| `# Refresh the materialized view so the inserted rows are visible to search` | Borrado — la línea que comentaba ya no existe |
| `# The other ingests and refresh must have executed despite the movies failure` | `# The other ingests must have executed despite the movies failure` |
| `"""Seed movies with punctuated titles, then refresh the materialized view."""` (fixture `punctuation_seeded_db`) | Explica que son buscables al instante |

Verificado: `grep -n "refresh\|materialized" tests/test_search.py` ya solo
devuelve la línea que menciona la feature 91 a propósito.

### 11.2 Deriva ORM↔DB en la nullabilidad de `search_vector`

Los modelos declaraban `nullable=False` y la DB decía `YES`. **Alineado hacia
el lado fuerte**: la migración ahora emite `... STORED NOT NULL`.

Es gratis y es cierto. Gratis porque la reescritura ya visita todas las filas,
así que la validación del `NOT NULL` no añade ninguna pasada. Cierto porque
`title` es `NOT NULL` en las cuatro tablas (verificado contra la DB) y
`overview` va dentro de un `COALESCE`, de modo que `to_tsvector` no puede
devolver `NULL`: no hay ningún riesgo de que el `ALTER` aborte a mitad del
despliegue por una fila que no cumpla.

Preferí subir la DB antes que bajar el ORM a `nullable=True` porque lo segundo
habría alineado los dos lados renunciando a declarar un invariante que sí se
cumple.

Verificado en base limpia: `information_schema.columns` devuelve `is_nullable =
NO` para las cuatro tablas, y el ciclo `upgrade → downgrade 0037 → upgrade`
vuelve a pasar. La aserción vive ahora en el propio test
(`test_every_content_table_has_a_stored_generated_vector_and_a_gin_index` filtra
por `is_nullable = 'NO'`, con el comentario de por qué), así que la deriva no
puede volver en silencio.

> Nota operativa: la DB de test local ya estaba en `0038` con la columna
> nullable, así que hubo que bajarla a `0037` y volver a subir para que el
> `ALTER` nuevo se aplicara. Cualquier entorno que ya tenga la `0038` puesta
> necesita lo mismo — en producción es irrelevante porque la `0038` no se ha
> desplegado todavía.

### 11.3 Hueco del runbook: el despliegue aborta después del `DROP` manual

Sección nueva en `docs/operations.md`, `#### Si el despliegue aborta después
del DROP manual`. Lo que cubre:

- **Cómo saber en qué caso estás**: `SELECT version_num FROM alembic_version`.
  `0038` → la migración entró y falló el arranque, `alembic downgrade 0037`
  recrea la vista solo. `0037` → la migración no entró y **ninguna herramienta
  te devuelve la vista**: el `downgrade` de la `0038` no se puede invocar desde
  `0037`. Hay que recrearla a mano.
- **Antes de recrearla, decidir.** Recrear la vista cuesta 137 MB y devuelve el
  cluster a 385 MB, es decir, al estado en el que la migración *no cabe*:
  habría que volver a dropearla antes del siguiente intento. Si el arreglo es
  de minutos, **no recrearla** y relanzar el despliegue. Recrearla solo si la
  vuelta va a durar horas.
- **El DDL de recuperación completo**, copiable, con los tres índices y la nota
  de que `uq_catalog_search_type_id` es obligatorio para `REFRESH ...
  CONCURRENTLY`. Es el de la `0031`, que es la definición vigente si la `0038`
  no entró.

Un dato que evita un `REFRESH` innecesario y que está escrito allí: `CREATE
MATERIALIZED VIEW` puebla la vista al crearla (`WITH DATA` es el defecto).

**Verificado, no supuesto.** Extraje el bloque SQL *del propio documento*
(para probar exactamente lo que el operador pegaría, escapado incluido), lo
ejecuté sobre una base a `0037` con la vista dropeada y comparé
`pg_get_viewdef` contra la que deja la `0037` limpia: **idénticas byte a
byte**. Después ejecuté un `REFRESH MATERIALIZED VIEW CONCURRENTLY` real sobre
el resultado — pasa, lo que demuestra que el índice único quedó bien.

### 11.4 Hueco del runbook: el nocturno en la ventana entre el `DROP` y el deploy

Sección nueva `#### Qué pasa si el nocturno dispara en esa ventana`. La
respuesta corta: **no revienta el job, solo ensucia el log**.

Lo comprobé leyendo el código que estará corriendo en esa ventana
(`git show HEAD:backlogg/scheduler/jobs.py`), no el nuevo:

- La llamada al refresco está envuelta en su propio `try/except` que solo
  loguea, en los tres sitios.
- Y es la **última** sentencia del bloque de sesión en los tres. Lo que
  escribió la rebanada ya está commiteado antes: `session.commit()` explícito
  en la ruta de `seed_targets` (movies/series) y `_persist_cursor`, que
  commitea, en las de books/games. Después del refresco solo se leen contadores
  en memoria, así que la transacción abortada no afecta a nada.
- Lo mismo vale para `scripts/backfill_sync.py` (reusa los mismos jobs) y para
  el fan-out de `/v1/search`, que tenía su propio `try/except`.

Resultado: el job sincroniza y avanza su cursor, `POST /v1/admin/sync/{type}`
devuelve 200 con sus contadores de siempre, la verificación de
`GET /v1/admin/stats` del workflow (`last_synced_at` < 2 h) pasa, y aparece una
línea de log con `relation "catalog_search" does not exist` (texto exacto
confirmado contra Postgres 16). Es ruido: ese refresco no iba a servir de nada.
**Lo único roto en la ventana es `/v1/search`, y lo está desde el instante del
`DROP`, dispare o no el nocturno.**

Cómo evitarlo de todos modos, para no mezclar señales al leer los logs del
despliegue: el cron es `0 2 * * *` **UTC** y el sync **no corre in-process** —lo
dispara GitHub Actions, porque en el free tier de Render APScheduler no llega a
ejecutarse—, así que basta con hacer el `DROP` **justo después de un run
nocturno**: ~24 h de margen. Si hay que desplegar cerca de las 02:00 UTC,
`gh workflow disable nightly-sync.yml` y `enable` tras el paso 4.

### Estado de `bash init.sh`

Sin cambios respecto al informe original: **ruff check OK, ruff format OK,
1.482 tests pasan**. Sigue fallando **solo** la sección 3, «Hay 2 features en
`in_progress` (máximo 1)», por la feature **74** parkeada a propósito. No la
toco: es estado de otra feature y las transiciones de estado son del leader.
Poniendo la 74 en `blocked` —estado que `init.sh` acepta y que describe
literalmente su situación— la sección 3 pasa y el script termina en verde.

### Archivos tocados en esta ronda

| Archivo | Cambio |
|---|---|
| `alembic/versions/0038_search_expression_index.py` | `... STORED NOT NULL` + comentario de por qué es gratis y cierto |
| `tests/test_search.py` | Cuatro comentarios/docstrings obsoletos sobre el refresco |
| `tests/test_search_expression_index.py` | La aserción de esquema exige además `is_nullable = 'NO'` |
| `docs/operations.md` | Dos subsecciones nuevas: recuperación tras un deploy abortado (con DDL verificado) y comportamiento del nocturno en la ventana |
