# impl — issue #18: slug vacío en alfabetos no latinos

**Rama:** `fix/non_latin_slug_fallback`
**Tipo:** bugfix (no está en `backend_feature_list.json`; `issues_list.json` no
tiene estado `in_progress`, así que el issue sigue en `open` — lo cierra el
leader tras el veredicto del reviewer, según `require_verification_to_close`).
**Decisión de producto aplicada:** opción B del plan — fallback por id externo,
**sin transliteración**.

---

## 1. Archivos

### Creados

| Archivo | Qué es |
|---|---|
| `backlogg/shared/slugs.py` | El helper compartido. Solo stdlib: no importa de ningún dominio (`docs/architecture.md`). |
| `tests/shared/test_slug_non_latin_fallback.py` | 72 tests: el helper, los 4 adaptadores, los 4 mapeadores de personas, la ruta por lotes y la ruta per-item. |

### Modificados

| Archivo | Cambio |
|---|---|
| `backlogg/movies/adapters/tmdb.py` | Borrada la copia local de `_slugify`; `movie_to_dict` usa `titled_slug(..., "TMDB", raw["id"])`. |
| `backlogg/series/adapters/tmdb.py` | Ídem sobre `series_to_dict`. |
| `backlogg/books/adapters/open_library.py` | Ídem sobre `book_to_dict`; el id sale de `search_doc["key"]` (`/works/OL…`). |
| `backlogg/games/adapters/igdb.py` | Ídem; el slug propio de IGDB sigue teniendo prioridad, el fallback solo entra si no hay ninguno. |
| `backlogg/admin/service.py` | Ídem; `_genres_payload` usa `slugify` compartido. |
| `backlogg/movies/service.py` | `_tmdb_person_row` usa `slug_with_external_fallback`; el slug de recomendación usa `titled_slug`. |
| `backlogg/series/service.py` | Ídem (cubre cast **y** `collect_series_creators`, que pasan por el mismo mapeador). |
| `backlogg/books/service.py` | `collect_book_authors` usa `slug_with_external_fallback` con el id de autor de OL. |
| `backlogg/trending/service.py` | Predice el slug con `titled_slug` para que la búsqueda local siga acertando. |
| `backlogg/people/repository.py` | `get_or_create_person_by_external` deriva el slug si le llega vacío (red de seguridad). |
| `docs/conventions.md` | Regla de slug: tabla de qué función usar, prohibición de slug vacío y de transliterar. |
| `docs/schema.md` | Qué garantiza el slug y qué no, en `## Item tables` y en `people`. |
| `docs/seeding-plan.md` | La segunda causa masiva de `unreachable`; matiz sobre `people_errors`. |
| `docs/architecture.md` | `shared/slugs.py` en el árbol. |

**No se ha tocado:** `.env`, migraciones, rutas ni `bruno/` (no hay endpoints
nuevos ni modificados).

---

## 2. Qué se implementó

### El helper (`backlogg/shared/slugs.py`)

Cuatro funciones. `slugify` es **copia literal** del cuerpo que estaba
duplicado en los cinco módulos, sin tocar una coma — esa era la condición para
no mover ni un slug del catálogo ya sembrado.

| Función | Qué hace |
|---|---|
| `slugify(text)` | El fold a ASCII de siempre. Devuelve `""` si no sobrevive nada. |
| `external_id_slug(source, external_id)` | `tmdb-1234567`, `open-library-ol123w`, `igdb-4567`. `""` si falta cualquiera de las dos mitades. |
| `slug_with_external_fallback(text, source, external_id)` | El fold, y si queda vacío el id externo. Es el punto de entrada para **personas**. |
| `titled_slug(title, year, source, external_id)` | El de **ítems**: sustituye a `f"{slugify(title)}-{year}"`. |

Detalles con intención:

- **`OPEN_LIBRARY` → `open-library`, no `open_library`.** El `\w` de la regex
  conserva el guion bajo, así que la fuente se normaliza (`_` → `-`) antes de
  foldarla. Sin esto el formato del plan no se cumplía.
- **Sin id externo, sin fallback.** `external_id_slug` devuelve `""` cuando
  falta `source` o `external_id`: un payload sin identidad no tiene de dónde
  derivar nada, y la validación de `bulk_load` **tiene que seguir viéndolo
  vacío** para descartarlo (punto 4 del plan).
- **El fallback de ítem no lleva año.** `titled_slug` devuelve `tmdb-305977`,
  no `tmdb-305977-2025`. El id ya es único; el año solo alarga la URL.
- **Mixto se queda con la parte latina.** `初次尝鲜 Season 2` → `season-2`. El
  fallback solo entra cuando el fold queda *totalmente* vacío. Es
  deliberado: si hay algo legible, un slug legible es mejor que uno opaco.

### Personas

Aplicado en los cuatro sitios donde nace un `BulkPerson` —
`_tmdb_person_row` de movies, `_tmdb_person_row` de series (que sirve a
`map_series_cast` **y** a `collect_series_creators`) y `collect_book_authors`—
más `get_or_create_person_by_external` en `people/repository.py`.

Ese último no construye el slug, lo recibe; le puse el fallback como **red de
seguridad** (`slug = slug or external_id_slug(source, external_id)`) porque es
el cuello de botella por el que pasan las dos rutas per-item
(`_persist_people_individually` de `scheduler/jobs.py` y las tres
`_get_or_create_person_*`). Un slug vacío ahí no es un slug feo: `upsert_person`
hace `ON CONFLICT DO UPDATE` sobre `uq_people_slug`, así que un solo caller
despistado vuelve a fundir a todo el mundo en una fila. Cuesta una línea y
cierra la clase entera de fallo.

### Ítems

Los cuatro adaptadores, sobre el `slug_base`, antes de pegar el año. Además dos
sitios que **predicen** el slug que producirá el adaptador para buscar primero
en local (`trending/service.py` ×2, `movies`/`series` `service.py` en
similar/recomendaciones): si no se cambian, quedan desalineados con el
adaptador. Y no era solo un fallo de caché — con el fold vacío la predicción era
`-2025`, así que la búsqueda local podía **acertar sobre un ítem que no era**
y devolver una película distinta de la pedida.

`games` es el caso raro: el slug lo trae IGDB. Se respeta; el fold del nombre
sigue siendo el primer fallback, y el id externo el segundo. De paso,
`raw.get("slug", ...)` pasó a estar guardado por un `or`, así que un `slug: ""`
o `slug: null` en el payload ya no se persiste tal cual.

### La validación que descartaba credits

**No se ha tocado** (`bulk_load.py:969`). Hay dos tests que fijan las dos mitades
del contrato: con nombres CJK/coreanos reales `people_rejected == 0` y las dos
personas aterrizan como filas distintas con sus credits; con un `BulkPerson` sin
`external_id` sigue valiendo 1.

---

## 3. Las dos exigencias explícitas

### No regresión sobre el catálogo ya sembrado

Dos comprobaciones, una sintética y otra empírica.

1. Una tabla de 10 títulos/nombres latinos (con acentos, `·`, `&`, `Æ`, `¿`,
   espacios de sobra) con el slug esperado escrito a mano, pasada por
   `slugify`, por `slug_with_external_fallback` y por los cuatro adaptadores.
2. **Auditoría de solo lectura contra la DB de dev** (script temporal, no
   versionado): para cada fila almacenada, recalcular el slug con el código
   nuevo y compararlo con el que hay en la tabla.

```
movies: 575 rows   | latin slugs changed: 0 | non-latin (esperado): 1
series: 1132 rows  | latin slugs changed: 0 | non-latin (esperado): 1
books:  389 rows   | latin slugs changed: 0 | non-latin (esperado): 2
games:  465 rows   | slugs vacíos hoy: 0
people: 11741 rows | latin changed: 0 | non-latin: 1 | sin external id: 22

   movies 137  '仙逆剧场版 弑仙之战'          ''      -> tmdb-1599191
   series 459  '初次尝鲜'                     '-2025' -> tmdb-305977
   books  404  '人間失格'                     '-1948' -> open-library-ol3923952w
   books  435  'Преступление и наказание'     '-1866' -> open-library-ol166894w
   people 1148 'Фёдор Достоевский'            ''      -> open-library-ol22242a
```

**Cero slugs latinos cambiados sobre 14.302 filas.** Las cinco únicas filas que
cambian son exactamente las cinco que midió el leader. Nota: el `external_id`
real de `movies id=137` es `1599191` (el leader no lo dio; lo saqué de
`external_ids`), y la persona 1148 resulta venir de **Open Library**, no de
TMDB — su fallback es `open-library-ol22242a`. Los tests usan estos ids reales.

### Sin colisiones nuevas

Cuatro tests dedicados: dos películas CJK del **mismo año**, dos series del
mismo año, dos libros del mismo año y tres personas de tres alfabetos distintos
(cirílico, chino, coreano) — todos con slugs distintos y ninguno vacío. Más el
test contra Postgres real, que comprueba que las dos personas acaban como dos
filas con dos ids y dos credits, no como una.

La unicidad no es estadística: `(item_type, source, external_id)` es única por
construcción (`uq_external_id`), así que `<fuente>-<id>` lo es también.

---

## 4. Sobre la migración de reparación: **no hace falta, y no la he escrito**

Coincido con el plan y añado el dato que faltaba: las filas degeneradas de la
DB de dev son **5 sobre 14.302** (0,035 %), y las cuatro de catálogo se
corrigen solas al re-hidratar porque su `external_id` sigue enlazado — el
próximo sync recalcula el slug… **salvo por un matiz que conviene tener claro**:

`_NEVER_UPDATED` en `bulk_load.py` incluye `slug` (es identidad), y
`upsert_movie` tampoco lo pisa. Es decir: **un re-sync no reescribe el slug de
una fila existente.** Las 5 filas de dev seguirán degeneradas hasta que se
borre la base. Como producción se borra y se siembra desde cero (que es
precisamente por lo que este issue se adelantó), el punto es irrelevante para
prod; para dev basta con borrar esas 5 filas a mano si molestan. Escribir una
migración de datos para 5 filas de una base que se va a vaciar sería trabajo
con riesgo y sin beneficio. Si el leader quiere limpiarlas igualmente, un
`DELETE` de 5 ids es más honesto que una migración; queda a su criterio.

---

## 5. Hallazgos colaterales (ninguno tocado)

1. **22 personas sin `external_id`** (0,19 % de 11.741), todas con nombre
   latino y slug correcto: `Steve Buscemi`, `Natalie Portman`, `Stanley
   Kubrick`… Son huérfanas de enlace, no de slug. Encaja con el issue #24
   (dos personas homónimas se funden en `uq_people_slug` y la perdedora se
   queda sin enlace) y con el issue #22 (`skipped_links`). Fuera de scope; el
   fallback por id externo no las alcanza porque su fold **no** está vacío.
2. **Géneros, plataformas y compañías no tienen fallback.** `slugify` a secas.
   Un género íntegramente en CJK produciría `""` y colapsaría igual. Hoy no
   pasa: TMDB e IGDB sirven esos nombres en inglés, y el vocabulario de libros
   es controlado (`docs/schema.md` § `book_genres`). Lo dejo fuera a
   propósito —el plan acota a personas e ítems— pero queda anotado: si algún
   día una fuente sirve un género localizado, el mismo bug reaparece ahí.
3. **`titled_slug` con `external_id = 0`** devuelve `tmdb-0`, no `""`. Es
   irrelevante en la práctica (ningún proveedor usa el 0) y determinista; lo
   menciono solo porque el test lo excluye a conciencia.
4. **Colisión teórica entre un slug de fallback y un título latino.** Una
   película que se llamase literalmente «Tmdb 1599191» chocaría con el
   fallback. Es la misma clase de colisión que ya existe entre dos títulos
   iguales del mismo año; no añade una categoría nueva de fallo.

---

## 6. Cómo verificarlo a mano

```bash
# 1. Los cinco casos reales medidos, sin red ni DB
uv run python - <<'PY'
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.series.service import collect_series_creators

print(TMDBClient().movie_to_dict(
    {"id": 1599191, "title": "仙逆剧场版 弑仙之战", "release_date": "", "genres": []})["slug"])
print(TMDBSeriesClient().series_to_dict(
    {"id": 305977, "name": "初次尝鲜", "first_air_date": "2025-01-10", "genres": []})["slug"])
print(OpenLibraryClient().book_to_dict(
    {"key": "/works/OL3923952W", "title": "人間失格", "first_publish_year": 1948})["slug"])
print(collect_series_creators([{"id": 3311, "name": "한영롱"}])[0].slug)
# tmdb-1599191 / tmdb-305977 / open-library-ol3923952w / tmdb-3311

# y la no regresión, que es la mitad que importa:
print(TMDBClient().movie_to_dict(
    {"id": 603, "title": "The Matrix", "release_date": "1999-03-30", "genres": []})["slug"])
# the-matrix-1999
PY

# 2. Los tests del issue, aislados
uv run pytest tests/shared/test_slug_non_latin_fallback.py -q     # 72 passed

# 3. Auditoría de no regresión contra la DB de dev (solo lectura).
#    El script del informe no está versionado; se rehace en 20 líneas:
#    para cada fila, recalcular titled_slug(title, year, source, external_id)
#    y comparar con la columna slug. Debe cambiar SOLO en las filas cuyo
#    slugify(title) sea "".

# 4. QA sobre la API (requiere `alembic upgrade head` en la DB de dev).
#    El sync de una serie con reparto CJK ya no debe devolver people_errors:
curl -s -X POST localhost:8000/v1/admin/sync/series -H "X-API-Key: $ADMIN_API_KEY" | jq
#    -> "people_errors": 0
```

Ojo con el punto 4: los ítems ya persistidos **no** cambian de slug al
re-sincronizar (`slug` está en `_NEVER_UPDATED`). Para ver el slug nuevo hace
falta un ítem que no exista todavía en la tabla, o borrar la fila antes.

---

## 7. `bash init.sh`

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
302 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
........................................................................ [  5%]
........................................................................ [ 10%]
........................................................................ [ 16%]
........................................................................ [ 21%]
........................................................................ [ 27%]
........................................................................ [ 32%]
........................................................................ [ 38%]
........................................................................ [ 43%]
........................................................................ [ 49%]
........................................................................ [ 54%]
........................................................................ [ 60%]
........................................................................ [ 65%]
........................................................................ [ 71%]
........................................................................ [ 76%]
........................................................................ [ 82%]
........................................................................ [ 87%]
........................................................................ [ 93%]
........................................................................ [ 98%]
.................                                                        [100%]
1313 passed in 105.13s (0:01:45)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

**1241 → 1313**: los 1241 anteriores siguen pasando, +72 nuevos.

---

# Ronda 2 — respuesta a CHANGES_REQUESTED

`bash init.sh` verde: **1322 passed** (1313 → +9). ruff check y format limpios.

## Punto 1 [MEDIA, el bloqueante] — tests de los cuatro sitios de predicción

Tenía razón el reviewer y la mutación lo demuestra: los cuatro cambios no
tenían nada que los sujetara. Cuatro tests nuevos en
`tests/shared/test_slug_non_latin_fallback.py`, uno por sitio:

| Test | Sitio que cubre |
|---|---|
| `test_trending_movie_predicts_the_slug_the_adapter_generates` | `trending/service.py:52` |
| `test_trending_series_predicts_the_slug_the_adapter_generates` | `trending/service.py:113` |
| `test_similar_movies_predicts_the_slug_the_adapter_generates` | `movies/service.py:303` |
| `test_similar_series_predicts_the_slug_the_adapter_generates` | `series/service.py:313` |

**Ninguno compara contra un literal.** Cada uno ejecuta la función real con
los externos mockeados, espía el `get_*_by_slug` para capturar el slug que la
función *predice*, y lo compara contra lo que el adaptador *genera* de verdad
para ese mismo ítem:

```python
expected = TMDBClient().movie_to_dict(dict(detail))["slug"]   # generación
...
assert seen == [expected, expected]                            # predicción
```

Además cada test llama a la función **dos veces** y exige
`detail_mock.assert_awaited_once()`: la segunda pasada tiene que acertar sobre
la fila que escribió la primera. Eso es la propiedad de usuario —predicción y
generación no pueden divergir— y no solo la cobertura de la línea. Es
importante porque, como dice el reviewer, compartir `titled_slug` unifica la
*regla* pero no impide que los *inputs* se separen: la predicción parte del
payload de lista y la generación del de detalle, que son dos dicts distintos.

### Evidencia de mutación

Revertidos los cuatro sitios a `f"{slugify(title)}-{year}" if year else slugify(title)`:

```
FAILED ...::test_trending_movie_predicts_the_slug_the_adapter_generates
FAILED ...::test_trending_series_predicts_the_slug_the_adapter_generates
FAILED ...::test_similar_movies_predicts_the_slug_the_adapter_generates
FAILED ...::test_similar_series_predicts_the_slug_the_adapter_generates
4 failed, 72 deselected

E  AssertionError: assert ['slug-predic...008', '-2025'] == ['slug-predic...'tmdb-771004']
E    At index 1 diff: '-2025' != 'tmdb-771004'
```

Y revertido **cada sitio por separado**, para confirmar que el mapeo es 1:1 y
que no hay un test que tape a otro:

```
mutado solo trending_movie   -> 1 failed, 3 passed  (test_trending_movie_…)
mutado solo trending_series  -> 1 failed, 3 passed  (test_trending_series_…)
mutado solo similar_movies   -> 1 failed, 3 passed  (test_similar_movies_…)
mutado solo similar_series   -> 1 failed, 3 passed  (test_similar_series_…)
```

Los cuatro archivos restaurados desde copia; `git status` no muestra residuo y
la suite completa vuelve a 1322.

## Punto 2 [BAJA] — la garantía falsa en `docs/schema.md`

Corregido, y sí estaba repetida en otro sitio: la había escrito igual de mal en
la sección `## Item tables` del mismo archivo y, en versión más suave, en
`docs/conventions.md`. Los tres dicen ahora lo mismo y con la distinción
explícita:

> El fallback cubre el fold **vacío**, no el fold **ambiguo**.

Con los dos ejemplos que lo demuestran —`宮崎駿 Jr` → `jr` y
`初次尝鲜 Season 2` → `season-2`— y diciendo que dos personas así siguen
fundiéndose por `uq_people_slug`, igual que dos homónimos latinos (#24). También
he quitado el mismo exceso del docstring de `slug_with_external_fallback`, que
decía «non-Latin input gets a unique, stable slug».

## Punto 3 [BAJA] — `titled_slug` puede devolver `""`: elijo **(a)**

**(a): el invariante se cumple de verdad, con guarda en la frontera de ítems.**
Y siguiendo el apunte del reviewer, la guarda **descarta el ítem**, no le
inventa un slug.

El razonamiento: `titled_slug` solo devuelve `""` cuando el fold está vacío
**y** no hay id externo. Un ítem sin id externo no puede tener fila en
`external_ids`, así que no se encontrará nunca por id, no se refrescará nunca y
se duplicará en cada sync — es el desastre de `skipped_links` que documenta
`docs/seeding-plan.md`. Y encima se queda con el slug `""`, sobre el que el
siguiente ítem igual de roto hará `ON CONFLICT DO UPDATE`: el fallo del issue
#18, un nivel más abajo. No es un ítem con un slug feo, es un ítem
impersistible. Se descarta y se cuenta.

Dos guardas, una por frontera de escritura de ítems, cada una reusando el
contador que ya está en el panel de ops:

| Frontera | Cómo | Se cuenta en |
|---|---|---|
| `bulk_load.py::bulk_load_items` | `RowRejected` con motivo legible, misma maquinaria que el resto de rechazos pre-validación | `rejected` |
| `scheduler/jobs.py::_write_items_individually` | `ValueError`, que cae en el `except` que ya existía | `errors` |

**Lo que NO he hecho, y por qué:** `titled_slug` **no** lanza. Un raise dentro
de un mapeador puro se propagaría a `movies/service.py:228`, al fan-out de
`search` y a `trending`, que hoy degradan con gracia y pasarían a devolver 500.
Esos caminos entran *por* el id externo (`/movie/{id}` siempre trae `id`), así
que no pueden alcanzar el caso: convertirlos en 500 sería pagar un riesgo real
por un caso inalcanzable. Tampoco he tocado los cuatro `upsert_*` de los
repositorios, por lo mismo.

Lo que sí queda cubierto es el agujero que el reviewer nombra —
`scheduler/jobs.py:812`, el `search_doc` construido a mano que copia
`"key": raw.get("key", "")`, exactamente la forma de error que fue el issue
#17 con `isbn`— porque las dos rutas de siembra/nightly/backfill pasan por una
de las dos guardas. Y `docs/conventions.md` lo dice explícitamente en vez de
fingir un invariante universal: nombra las dos guardas, dice que `titled_slug`
no lanza y por qué, y recuerda que en personas la red está en
`get_or_create_person_by_external`.

Cuatro tests nuevos:

- `test_book_to_dict_yields_an_empty_slug_without_a_work_key` — fija la
  precondición (el `search_doc` sin `key`).
- `test_bulk_load_items_rejects_an_item_with_no_slug` — `(written, rejected) ==
  (0, 1)` y ninguna fila con `slug = ''`.
- `test_write_items_individually_rejects_an_item_with_no_slug` — `(0, 1, 0)`.
- `test_a_normal_book_still_goes_through_both_frontiers` — la guarda no le
  cuesta la fila a un libro no latino legítimo (`open-library-ol771111w`).

## Los dos apuntes no bloqueantes

- **Los 29 tests que también pasan en `main`**: entendido, son pines de no
  regresión y se quedan; no he añadido ni uno más de esa clase.
- **El literal repetido nueve veces**: arreglado.
  `test_slug_with_external_fallback_uses_the_external_id` es ahora una tabla de
  10 casos donde cada alfabeto va con la fuente de la que viene de verdad
  (CJK/coreano → TMDB, ruso/árabe/griego/hebreo → Open Library, japonés →
  IGDB) y cada uno espera su propio slug.

## Archivos tocados en esta ronda

| Archivo | Cambio |
|---|---|
| `tests/shared/test_slug_non_latin_fallback.py` | +8 tests (4 predicción, 4 guarda) y la parametrización con variedad real. 81 tests en el archivo. |
| `backlogg/shared/bulk_load.py` | Guarda de slug vacío en `bulk_load_items`. |
| `backlogg/scheduler/jobs.py` | Guarda de slug vacío en `_write_items_individually`. |
| `backlogg/shared/slugs.py` | Docstrings: quitado el exceso de `slug_with_external_fallback`; `titled_slug` documenta que puede devolver `""`, que no lanza a propósito y quién lo recoge. |
| `docs/schema.md` | Reformulada la garantía en `people` y en `## Item tables`. |
| `docs/conventions.md` | Fold vacío vs. ambiguo; apartado «Quién hace cumplir *nunca vacío*». |

Sigue sin haber migración, sin tocar `.env`, sin cambios de endpoints (nada que
sincronizar en `bruno/`) y sin commit.
