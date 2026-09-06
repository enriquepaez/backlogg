# Feature 87 — `openlibrary_dump_seeding` (informe del implementer)

**Rama:** `feat/openlibrary_dump_seeding` · **Fecha:** 2026-09-04
**Veredicto propio:** implementada y verificada. `bash init.sh` en verde.

---

## 1. Qué se ha hecho, en una frase

La siembra del catálogo de libros ya no sale de `search.json`: cuatro pasadas en
streaming sobre los dumps mensuales de Open Library producen el catálogo entero
con **cero** peticiones HTTP por libro y por autor, y lo escriben por la ruta de
lotes que ya existía. El camino de la petición —`search_book`, el fallback
on-demand, `get_book`— y el job nocturno `sync_books` **no se han tocado**.

## 2. Archivos

### Nuevos

| Archivo | Qué es |
|---|---|
| `backlogg/books/adapters/openlibrary_dump.py` | El pipeline. Parseo de las dos formas de dump, agregación por obra, filtro de la feature 73 y el puente al `search_doc` que consume `book_to_dict`. Las funciones de agregación reciben **iterables de líneas**, no clientes HTTP: los tests no necesitan red |
| `scripts/seed_openlibrary_books.py` | Hermano de `scripts/seed_tmdb_targets.py`: cinco fases, artefacto por fase, contadores y códigos de salida documentados |
| `tests/books/test_openlibrary_dump.py` | **56** tests unitarios de las funciones puras (52 en la ronda 1) |
| `tests/books/test_openlibrary_dump_fixture.py` | **El test del criterio 4**: 12 tests que comparan el camino de dumps contra el de `search.json` para las mismas obras |
| `tests/test_openlibrary_dump_seeding.py` | **22** tests de las cinco fases contra la DB real (12 en la ronda 1): siembra, géneros, credits, idempotencia, salto de fase, `--force`, escritura atómica, códigos de salida y —añadidos en la ronda 2— los tres runs degradados y el cableado hasta `main()` |
| `tests/books/dump_fixtures.py` | Localiza y lee el fragmento (no es módulo de test) |
| `tests/books/fixtures/openlibrary_dump/` | El fragmento: `reading_log.tsv`, `editions.tsv`, `works.tsv`, `authors.tsv`, `search_docs.json` y un `README.md` de procedencia. 92 KB en total |

### Modificados

| Archivo | Cambio |
|---|---|
| `backlogg/scheduler/jobs.py` | Renombrados `_BatchWriter` → `BatchWriter` y `_refresh_catalog_search` → `refresh_catalog_search`. **Sin cambio de comportamiento** |
| 9 archivos de `tests/` | El mismo renombrado, mecánico (`sed`) |
| `backlogg/core/config.py` | Corregido el comentario falso y documentada la inercia parcial de `SEED_TOP_N_BOOKS` |
| `.github/workflows/backfill-sync.yml` | `mode=dump` nuevo (solo `book`), inputs `dump_phase`/`force_phase`, caché del work-dir y mensaje de error de `enumerate` corregido |
| `docs/external-apis.md` | Rate limits reales + sección entera de dumps |
| `docs/seeding-plan.md` | §3 reescrita: tamaños medidos y muerte de la vía B |
| `docs/operations.md` | Sección `mode=dump` con coste medido de tiempo, disco y memoria |
| `.gitignore` | `.openlibrary-seed/`, el work-dir por defecto del script |
| `docs/architecture.md` | (ronda 2) `seed_openlibrary_books.py` añadido a la lista de scripts |
| `progress/current.md` | Marcada la casilla del implementer |

`bruno/` **no cambia**: la feature no añade, modifica ni elimina ningún
endpoint (comprobado: el script es un script, igual que `seed_tmdb_targets.py`,
justo para no meter superficie HTTP nueva). Tampoco hay migración Alembic: no se
toca el esquema.

## 3. Decisiones y por qué

### 3.1 Vía A (dump de editions), y no por preferencia

Confirmado con datos: **casi todos** los campos de selección los calcula Solr
desde las ediciones, no desde la obra. Medido sobre las 5 obras del fragmento,
`edition_count`, `number_of_pages_median`, `language`, `first_publish_year`,
`ddc`, `lcc` e `isbn` salen todos de agregar ediciones — y una obra **no tiene
idioma**: el `language` de `search.json` es la unión del de sus ediciones. La
«vía B» del plan (clasificar desde works y pedir `ddc`/`lcc` a `search.json`)
no permitiría ni *seleccionar* el catálogo. Queda descartada por los hechos.

### 3.2 El orden de las pasadas es el diseño

```
1. reading-log (0,12 GB) -> COUNT(*) por obra -> whitelist: 399.259 obras >= 5
2. editions   (12,59 GB) -> agrega SOLO la whitelist, y aplica ya el filtro de
                            la feature 73 -> ~19 k obras elegidas
3. works      (4,06 GB)  -> solo las elegidas
4. authors    (0,78 GB)  -> solo las claves de autor recogidas
```

La whitelist es lo que acota la memoria de la pasada grande. Y aplicar el filtro
de la feature 73 **al final de la fase 2** (no en la 3) reduce el artefacto y la
memoria de las fases 3-5 de 399 k a ~19 k obras, porque para entonces ya se
conocen los cuatro discriminantes.

Optimización medible añadida: la fase 2 no hace `json.loads` de las 56,7 M de
líneas. Extrae las claves de obra de la línea **cruda** con un regex y solo
parsea si alguna está en la whitelist; las fases 3 y 4 miran antes la columna
`key`. `json.loads` es, de lejos, lo más caro de estas pasadas.

### 3.3 Reutilizar la clasificación, no duplicarla

`build_search_doc` monta un dict con la **misma forma** que devuelve
`search.json` y el script se lo pasa a `OpenLibraryClient.book_to_dict`. Géneros
(feature 72), slug con el fallback del issue #18 y forma del dict salen del
mismo código que usa el camino on-demand. `book_to_dict` **no se ha tocado**:
acepta el doc del dump tal cual.

Dos decisiones finas dentro de ese puente:

- **`first_publish_year` sale del `min` de las ediciones**, y el
  `first_publish_date` de la obra se ignora deliberadamente aunque exista.
  Motivo: Solr también lo ignora, y leerlo movería el año y **con él el slug**
  respecto a los libros ya sembrados por `search.json`, que se upsertan por
  slug. Sería duplicar catálogo en vez de refrescarlo.
- **`subject_facet` = los `subjects` de la obra.** Medido sobre las 5 obras del
  fragmento: el `subject_facet` de Solr es **exactamente** la lista `subjects`
  del registro de obra, misma cardinalidad y mismos valores (14/14, 27/27, 7/7,
  13/13, 0/0). No hace falta agregar subjects de ediciones.

### 3.3 bis. Dónde el camino de dumps se aparta de `search.json`, a propósito

Dos campos **no** coinciden, y están fijados con un test para que sigan siendo
deliberados (`test_the_two_deliberate_divergences_from_the_search_json_path`):

- **`isbn`**: una obra tiene una fila y muchas ediciones, así que «el» ISBN es
  una elección en los dos caminos. `search.json` devuelve su propio orden; el
  dump coge la primera edición que encuentra prefiriendo ISBN-13. El del dump es
  al menos determinista (orden de clave de edición en el dump) y consistentemente
  ISBN-13 cuando existe, cosa que el de Solr no es. Medido: difiere en las 4
  obras seleccionadas del fragmento.
- **`overview`**: el camino de dumps **lo rellena** con la `description` de la
  obra, que el nocturno por `search.json` nunca tiene (llama a `book_to_dict`
  con `work_detail=None` para no pagar una petición más por libro). En el dump
  la descripción no cuesta nada, así que los libros sembrados salen con sinopsis
  —la misma que ya les da el camino on-demand—. Es una mejora, no una deriva.

### 3.4 Escritura: ni una línea nueva

`bulk_load_items` con el `BOOK_BULK_SPEC` que ya existía, a través del
`BatchWriter` de `scheduler/jobs.py`. Se propagan `errors`, `people_errors` y
`skipped_links` (`collect_link_skips`) igual que en los jobs.

**Sobre el renombrado**: el script necesita exactamente las mismas garantías que
el nocturno (lotes acotados, commit por lote, y caída a la ruta por ítem si un
lote falla). Duplicar esa lógica habría sido peor que hacer público un nombre
que ya se comparte entre módulos. El cambio es un `sed` sin efectos: los 1.397
tests pasan.

### 3.5 Autoría sin una sola petición

`author_rows` produce `BulkPerson(role="AUTHOR", source="OPEN_LIBRARY", ...)`
con `slug_with_external_fallback`, el mismo contrato de retorno de
`collect_book_authors` — que **no se toca**, porque es del camino on-demand. Un
autor ausente del dump degrada a un credit menos, nunca a un libro perdido.

### 3.6 Reanudabilidad por fases

Cada fase deja un artefacto comprimido en `--work-dir` y se salta si ya existe
(`--force` lo rehace). Los artefactos se escriben a `.tmp` + `rename`, así que
un run muerto a media escritura nunca deja un artefacto truncado del que fiarse
(hay test). La fase 5 no necesita artefacto: es un upsert, idempotente por
construcción (hay test). En Actions el work-dir va a `actions/cache` con
`restore`/`save`, para que la reanudación funcione **entre dispatches**, que es
donde de verdad ocurre: cada dispatch es un runner nuevo.

## 4. Lo que medí de verdad, y lo que asumí

### 4.1 Medido contra las fuentes reales (2026-09-04)

| Qué | Cómo | Resultado |
|---|---|---|
| Tamaños de los dumps | `HEAD` sobre `openlibrary.org/data/` | editions 12,59 GB · works 4,06 · authors 0,78 · reading-log 0,12 |
| Formato TSV de 5 columnas, sin cabecera, JSON escapado | leyendo bytes reales de los 4 dumps | confirmado |
| **`reading-log` NO es ese formato** | ídem | son **4 columnas** `work_key \t edition_key \t shelf \t date`, sin JSON. El plan lo daba por hecho pero no lo decía; el parser es distinto |
| Las cuatro baldas | pasada completa | `Want to Read` 10.558.404 · `Already Read` 1.672.281 · `Currently Reading` 605.949 · `Stopped Reading` 1.392 |
| Whitelist | pasada completa | 12.838.026 filas, 3.314.590 obras, **399.259 con >= 5** |
| Tamaño de cada dump en líneas | pasadas completas | reading-log 12.838.026 · works **41.591.088** · authors 15.412.139 · editions **56.728.501**. El plan hablaba de «~39 M de obras» y «~53 M de ediciones»: se quedaban cortos, como los tamaños en GB |
| Ancho de banda a archive.org | descarga de 200 MB | **6,25 MB/s**. El run es limitado por red |

### 4.2 El punto que el plan pedía demostrar: ¿tragan los parsers el formato CRUDO?

**Sí. Medido, no leído.** Los dos lados reciben texto distinto y producen los
mismos géneros:

| Obra | `ddc`/`lcc` del **dump** (crudo) | `ddc`/`lcc` de **Solr** (normalizado) | Géneros dump | Géneros Solr |
|---|---|---|---|---|
| `OL24178205W` | `813/.6` · `PS3608.A98845L68` | `813.6` · `PS-3608.00000000.A98845L68` | `fiction, literature` | `fiction, literature` |
| `OL18108064W` | — · `GV697.G6G6 2018`, `V63.G58 A3 2018` | — · `GV-0697.00000000.G6G6 2018` | `sports-recreation` | `sports-recreation` |
| `OL8960135W` | — · `GV1061.15.K39 A3 2006` | — · `GV-1061.15000000.K39A3 2017` | `sports-recreation` | `sports-recreation` |
| `OL17508740W` | sin `ddc` ni `lcc` | sin `ddc` ni `lcc` | `fiction, childrens-young-adult` | `fiction, childrens-young-adult` |
| `OL24456878W` | sin nada | sin nada | (ninguno) | (ninguno) |

Y los cuatro agregados que alimentan el filtro de la feature 73 coinciden
**exactamente** con los de `search.json` para las 5 obras: `edition_count`
(13/12/11/11/2), `number_of_pages_median` (398/851/364/295/205), la unión de
idiomas y `first_publish_year`. Son asserts del test, no una tabla decorativa.

### 4.3 Lo que asumí (y no pude medir)

- ~~El pico de memoria de la fase 2~~ — **ya no es una asunción**: 574 MB
  medidos en una pasada completa (§7).
- **El tiempo en un runner de GitHub Actions.** Lo medido es desde una línea
  doméstica de 6,25 MB/s. En Actions la salida suele ser más rápida, así que lo
  documentado es un techo razonable, no una predicción.
- ~~El tamaño exacto del catálogo resultante~~ — **también medido**: 19.221
  obras, +1,8 % sobre las 18.874 de `numFound` (§7). No coinciden al ítem, y no
  tienen por qué: el dump es del 31-08 y el Solr, de hoy.

## 5. Los 11 criterios de aceptación, uno a uno

| # | Criterio | Cómo se cumple |
|---|---|---|
| 1 | Dumps en streaming, sin descomprimir a disco ni cargar en memoria | `stream_dump_lines` = `httpx.stream` + `gzip.GzipFile` sobre un file-like que envuelve el iterador de chunks. **Ningún byte de dump toca el disco**. Test: `test_stream_dump_lines_decompresses_the_response_on_the_fly` (con `httpx.MockTransport`). La memoria la acota la whitelist, no el corpus |
| 2 | Decisión razonada y documentada sobre `ddc`/`lcc` | Vía A, y la vía B **no existe** (§3.1). Documentado en `docs/seeding-plan.md` §3 y `docs/external-apis.md` con la tabla campo→origen |
| 3 | `SEED_TOP_N_BOOKS` coherente y comentario corregido | `backlogg/core/config.py`: el «comfortably above» ya no está; se dice que es **inerte para la siembra** (selección por umbral, sin corte por número de ítems) y **vigente para el camino por cursor**. Replicado en `docs/operations.md` y `docs/seeding-plan.md`. Y **no lo he dejado a medias**: el valor de producción (10.000) es *incoherente* con las 18.874 obras que el filtro entrega de verdad, así que el cursor da la vuelta antes de recorrer el catálogo. No cambio una env var de Render por mi cuenta: queda señalado en los dos sitios como algo a subir a ≥ 18.874 **si** se sigue usando ese camino |
| 4 | Se preservan las features 72 y 73, con test sobre datos reales de dump | `tests/books/test_openlibrary_dump_fixture.py`, 12 tests. Compara contra lo que produce `book_to_dict` con el doc de `search.json`, **nunca contra literales**. Resultados en §4.2 |
| 5 | Autoría desde `ol_dump_authors` | `collect_author_names` + `author_rows`. Cero llamadas a `get_author`. El `author_name` del search doc no se usa: el pipeline ni lo pide |
| 6 | Pipeline reanudable | Artefacto por fase + salto de fase + escritura atómica + caché del work-dir en Actions. Tests: `test_a_phase_with_an_artifact_is_skipped` (con un stream que **explota** si lo llaman), `test_force_redoes_a_phase_with_an_artifact`, `test_artifacts_are_written_atomically` |
| 7 | Coste en tiempo y disco documentado en `docs/operations.md` | Sección *Siembra de libros desde los dumps de Open Library*: tabla por fase con líneas leídas y tiempo medidos, pico de disco (**el work-dir**, no el dump) y pico de memoria |
| 8 | `search.json` sigue sirviendo el fallback y la búsqueda | `sync_books`, `search_book`, `get_book`, `_persist_book_authors` y `collect_book_authors` **sin cambios de comportamiento**. Lo único que tocó `jobs.py` es el renombrado de dos nombres. Los 1.412 tests, incluidos los del nocturno, pasan |
| 9 | `docs/external-apis.md` y `docs/seeding-plan.md` actualizados | Sí, y de paso corregida la línea falsa «Rate limits: none enforced» (1 req/s sin identificar, 3 con UA, prohibido el bulk harvesting) → issue #26 |
| 10 | Tests sobre un fragmento fijado en el repo, sin red | `tests/books/fixtures/openlibrary_dump/`, 92 KB de líneas **verbatim** del dump `2026-08-31`. Ningún test de la suite toca la red |
| 11 | `bash init.sh` en verde | Sí: lint, formato y **1.414 tests** tras la ronda 3 (+92 sobre los 1.322 de partida: 1.398 al cerrar la ronda 1, 1.412 la ronda 2). Salida de la ronda 1 en §10 |

## 6. El fragmento del repo (patrón nuevo)

No había ni un fixture en fichero en toda la suite. Va en fichero porque **el
objeto bajo prueba es el formato**: una línea reescrita a mano probaría que sé
escribir el ejemplo que ya sé parsear. Está en `tests/books/fixtures/` —al lado
del dominio que lo usa, siguiendo el corte vertical— y tiene su `README.md` con
la procedencia exacta, qué obra cubre qué caso y qué se truncó y por qué.

Cinco obras reales cubren: inglés que pasa con `ddc`+`lcc`, inglés sin `ddc` y
con `lcc` multiclase, inglés sin ninguna de las dos, castellano que pasa por los
suelos ES, e inglés que **no** pasa por 19 estanterías contra un suelo de 20.
Más los casos de borde que pedía el plan: JSON con comillas y escapes `\uXXXX`,
edición sin `languages`, obra sin `ddc` ni `lcc`, autor ausente del dump de
authors y edición cuyo `works[]` apunta fuera de la whitelist. Y cuatro obras de
contorno con **todas** sus filas reales de reading-log y recuentos exactos de 4,
5, 19 y 20, que clavan los dos umbrales donde de verdad están.

## 7. Coste real del run (medido, no estimado)

Run instrumentado con el **código de esta rama** contra el dump `2026-08-31`
(`resource.getrusage(RUSAGE_SELF)`, pasadas completas, no muestreo):

| Fase | Líneas leídas | Tiempo | Pico de RSS | Artefacto |
|---|---|---|---|---|
| 1 `reading-log` | 12.838.026 | **61 s** | **444 MB** | 1,4 MB (399.259 obras) |
| 2 `editions` | 56.728.501 | **7.516 s** (125 min) | **574 MB** | 1,7 MB (**19.221 obras elegidas**) |

Y lo que la fase 2 reporta además: de las 399.259 obras de la whitelist,
**392.466** tienen al menos una edición en el dump, y **19.221** pasan el filtro
de la feature 73.

**Tres cosas que salen de aquí:**

1. **El pico de memoria es 574 MB**, el número que faltaba (B3). La cota
   funciona: agregar 56,7 M de ediciones cuesta medio giga porque solo se
   guardan las 399 k obras de la whitelist. En un runner de 16 GB sobra.
2. **El pico de disco es 3,1 MB** tras las dos primeras fases — los artefactos,
   no el dump. Los 17,5 GB son tráfico, no almacenamiento. (Mi estimación previa
   de «100-200 MB de artefactos» era un orden de magnitud alta.)
3. **19.221 obras elegidas contra las 18.874 que daba `search.json`: +1,8 %.**
   Es el contraste más fuerte del criterio 4 y no lo tenía antes: reproducir el
   filtro de la feature 73 sobre el dump da el mismo catálogo que Solr, medido a
   escala completa y no sobre cinco obras.

**Los tiempos varían muchísimo por el ancho de banda de archive.org**: la misma
pasada de editions, mismo código y misma línea, tardó **35 min** a las 15:00 y
**125 min** a las 19:00 del mismo día. `docs/operations.md` da el rango, no el
número bueno.

Las fases 3 y 4 llevan en `docs/operations.md` el tiempo de una pasada
equivalente sobre los mismos ficheros (~14 min y ~3 min); su memoria es
trivialmente menor porque trabajan sobre 19.221 obras, no sobre 399.259.

## 8. Dos cosas que medí y salieron distintas de lo que había escrito

### 8.1 `publish_date` y el `\b` que rechaza "c1985" (bug mío, arreglado)

`publish_date` es texto libre de verdad. Mi primera versión anclaba el año con
`\b`, y eso rechaza **`"c1985"`** (circa): `c` y `1` son ambos caracteres de
palabra, así que no hay frontera entre ellos. El agregado salía con
`first_publish_year=None` y el libro se sembraba sin fecha.

Arreglado cambiando la frontera de palabra por una guarda sobre **dígitos**:
`(?<!\d)(1\d{3}|20\d{2})(?!\d)`. Acepta las formas reales del corpus —`2005`,
`2005-03-17`, `February 27, 1997`, `Dec 04, 2018`, `nov 15 2018`, `4/12/2018`,
`28 septembre 2023`, `Octubre 2021`, `c1985`, `[1985]`, `1985?`— y sigue
rechazando lo que debe: una tirada de más de cuatro dígitos (ISBN, LCCN, OCLC).
Los 15 casos están parametrizados en el test.

### 8.2 La mediana de páginas: `ceil`, no `int` (asunción mía, corregida)

Escribí `int(statistics.median(...))` y lo di por bueno porque coincidía con
`number_of_pages_median` en las 5 obras del fragmento. **La comprobación no
valía**: ninguna de las 5 cae en el caso que distingue las dos funciones (una
mediana en `.5`, es decir un número par de ediciones con páginas). Fui a la
fuente de Open Library (`openlibrary/solr/updater/work.py`) y dice
`ceil(median(number_of_pages))` sobre las ediciones cuyo `number_of_pages`
`is not None`. Dos correcciones, las dos ahora con test:

- `math.ceil` en vez de `int`. Redondear al revés movería una obra una página
  respecto a `BOOKS_SEED_MIN_PAGES`.
- un `number_of_pages` de **0 vota**, porque upstream solo salta los `None`. Yo
  lo estaba descartando.

Es el ejemplo de por qué el fragmento, siendo real, no es suficiente por sí
solo: cubre lo que cubre, y lo que no cubre hay que ir a buscarlo a la fuente.

## 9. Lo que he dejado fuera, a propósito

- **El nocturno sigue en `search.json`.** El incremental desde dumps es la
  feature 88 (`docs/seeding-plan.md` §6).
- **`BOOK` no entra en `SEED_TARGET_SOURCES`.** No hay fase de hidratación por
  ítem que necesite una lista de trabajo persistida.
- **`User-Agent` y limitación de ritmo en el adaptador on-demand**: issue #26,
  registrado por el leader. Otro camino, otra causa.
- **No he arreglado nada preexistente de paso.** No encontré bugs ajenos a la
  87 en el código que toqué.

## 10. Salida de `bash init.sh`

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
308 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
1398 passed in 129.74s (0:02:09)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(Exit code 0. Se han recortado las líneas de puntos de pytest y el `warning`
repetido de `uv` sobre `tool.uv.dev-dependencies`, que es previo a esta rama.)

## 11. Autoevaluación contra `CHECKPOINTS.md`

| | |
|---|---|
| **C1** `init.sh` sin errores | ✅ exit 0, §10 |
| **C2** sin `print()` de debug | ✅ |
| **C3** sin TODOs sueltos | ✅ |
| **C4** `ruff check` + `format --check` | ✅ |
| **C5** todos los tests pasan | ✅ 1.414 (ronda 3) |
| **C6-C8** modelos y migraciones | n/a — la feature no toca el esquema, así que **no hay migración** |
| **C9-C13** endpoints | n/a — no se añade ninguno; por eso `bruno/` no cambia |
| **C14** fechas de APIs externas convertidas explícitamente | ✅ el año del dump entra como `int` y `book_to_dict` construye el `date`; `last_synced_at` sale como `datetime` |
| **C15** ids externos únicos por test | ✅ los 5 OLIDs del fragmento no aparecen en ningún otro test de la suite (comprobado con `grep`), y el fixture `db` hace rollback por test |
| **C16-C17** fallback on-demand | n/a — esta feature no lo toca (y ese es justo el criterio 8) |
| **C18** sync idempotente | ✅ `test_seeding_twice_neither_duplicates_nor_loses` |
| **C19** un error no aborta el resto | ✅ **ronda 2**: además de lo que hereda de `BatchWriter`, el mapeo por ítem va en `try/except` y hay un test de obra envenenada (la review lo dejó en `[ ]` con razón) |
| **C20-C22** separación de capas | ✅ el adaptador no importa SQLAlchemy; la escritura pasa por `bulk_load_items` con el spec del repositorio |

---

# Ronda 2 — respuesta a `progress/review_87.md` (CHANGES_REQUESTED)

La review acertó donde dolía: **la fase de escritura era la única parte sin test
del camino degradado**, y es justo la parte que no me dio tiempo a cerrar antes
del corte de la ronda 1. Todo lo señalado está resuelto; abajo, hallazgo por
hallazgo, qué hice y qué comprobé.

`bash init.sh` **verde: 1412 tests** (+14 sobre los 1398 de la ronda 1).

## Bloqueantes

### B1 — Los tres contadores de `phase_load` no los sujetaba nada

**Resuelto con tres tests de run degradado contra la DB real**, uno por
contador, cada uno con una degradación distinta y realista:

| Test | Degradación | Qué afirma |
|---|---|---|
| `test_a_work_that_cannot_be_mapped_costs_only_that_work` | `book_to_dict` revienta para **una** obra | `errors == 1`, `synced == 3`, la obra envenenada no tiene fila ni link, las otras sí, y `_exit_code(summary) == 2` |
| `test_a_rejected_credit_is_counted_and_never_costs_the_book` | un `BulkPerson` con `slug` vacío (payload incompleto, que el cargador por lotes descarta) | `people_errors > 0`, `synced == 4`, `errors == 0`, 0 credits en DB, exit 2 |
| `test_an_external_id_that_cannot_be_linked_is_reported` | una fila anterior ya posee la terna `(BOOK, OPEN_LIBRARY, OL24178205W)` bajo otro slug — el escenario del issue #22, un título que cambió entre dos siembras | `skipped_links == 1`, `synced == 4`, la fila vieja conserva el id, exit 2 |

Y el último eslabón, que la review señalaba como no probado (`writer.errors →
summary → _exit_code → código de salida`): `test_main_turns_a_degraded_summary_into_exit_2`
pasa por `main()` de verdad y comprueba **el 2 y el log de `DEGRADED`**, más
`test_main_returns_0_on_a_clean_summary` y `test_main_returns_1_when_the_run_blows_up`.
Los tres van con un `run` falso porque `main` es dueño del bucle de eventos
(`asyncio.run`) y no puede llamarse desde dentro de uno; la otra mitad —que un
run degradado de verdad **produzca** ese summary— es lo que afirman los tres
tests de arriba contra la base de datos.

**Verificado por mutación, como pedía la review**: puse los tres contadores a
`0` constante, uno por uno, y **cada mutación mata un test** (antes sobrevivían
las tres). Restaurado el fichero y comprobado por `md5sum`.

### B2 — El mapeo por ítem estaba desnudo

`build_item` va ahora dentro de `try/except`, cuenta `mapping_errors` y sigue,
exactamente como `sync_books` (`jobs.py:809-838`). El contador se suma a
`errors` del summary, así que una obra inmapeable degrada el run (exit 2) en vez
de abortarlo. Mutación comprobada: quitando el `try/except`, el test de la obra
envenenada falla. **C19 queda cubierto.**

### B3 — La §7 del informe prometía un número que no existía

**Rellenada con el run instrumentado que terminó mientras tanto**, y el número
que faltaba es el pico de memoria de la fase 2: **574 MB**. De paso trajo dos
datos que no tenía:

- **19.221 obras elegidas** contra las 18.874 de `search.json`: **+1,8 %**. Es
  el contraste del criterio 4 hecho a escala completa, no sobre cinco obras.
- **Pico de disco real: 3,1 MB** de artefactos tras las dos primeras fases. Mi
  estimación previa («100-200 MB») era un orden de magnitud alta, y así lo digo.

Las dos referencias cruzadas del §4.3 dejan de ser promesas: ahora son datos
medidos, y las marco tachadas para que se vea qué dejó de ser asunción.

## No bloqueantes — todos cerrados

1. **Guarda interna de whitelist en `aggregate_editions`**: clavada con
   `test_aggregate_editions_drops_the_works_of_a_shared_edition_that_are_not_wanted`.
   Mutación comprobada (borrar la guarda mata el test).
   **Con una salvedad que digo en vez de esconder**: esa línea es **sintética**,
   no del fragmento real, y el test lo declara en su docstring. Busqué el caso y
   **no aparece** donde puedo mirar: **0 ediciones con más de una entrada en
   `works[]`** entre las 49 reales del fixture y **0** en las 6.430 primeras
   líneas del dump de editions (la muestra que bajé al construirlo). No afirmo
   que no exista en los 56,7 M — afirmo que no lo encontré donde busqué, así que
   el caso hay que construirlo. Y aun así hay que sujetarlo, porque es la guarda
   que acota la memoria de la pasada de 12,59 GB. Meter esa línea en el fragmento habría roto la afirmación
   «verbatim» de su README, que es justo lo que el reviewer verificó con lupa;
   por eso va inline en el test unitario, donde el fichero ya usa dicts inline.
2. **`select_works` solo lo usaban los tests**: `phase_editions` ahora **lo
   llama**. Se acabó la copia; el test del criterio 4 y el script corren la
   misma función. Comprobado en el run real de la fase 2 (19.221 obras).
3. **Las otras cuatro mutaciones supervivientes**, cerradas con un test cada una,
   y las cuatro **verificadas por mutación**:
   - `test_a_work_with_no_title_is_dropped_and_counted` (guarda de `untitled`),
   - `test_phase_selects_only_the_requested_phase` (`--phase` de verdad restringe),
   - `test_the_load_phase_refreshes_the_search_view` (`refresh_catalog_search`),
   - `test_seeded_books_carry_the_synopsis_from_the_works_dump` — el que faltaba
     de verdad: el `overview` que el §3.3 bis presenta como mejora deliberada
     ahora se afirma **en la fila de la DB**, no solo en el adaptador.
4. **Trampa de la caché de Actions**: arreglada, no solo avisada. Restaurar el
   work-dir es ahora **opt-in** (`-f resume=true`); el `mode=dump` normal
   —el que `docs/operations.md` documenta— empieza siempre del dump del mes en
   curso y no puede resucitar el catálogo de un dump viejo en silencio. Guardar
   sigue siendo incondicional (`always()`), que es lo que hace que un run muerto
   a medias se pueda continuar. Documentado con los dos comandos.
5. **`docs/architecture.md`**: añadido `seed_openlibrary_books.py` a la lista de
   scripts.
6. **`sys.intern`: la review tenía razón, y lo medí.** Sobre las 19.221 obras
   del run real:

   | Campo | Valores | Distintos | Ratio | Decisión |
   |---|---|---|---|---|
   | `languages` | 59.482 | 216 | 275× | internar |
   | `ddc` | 115.934 | 10.717 | 10,8× | internar |
   | `lcc` | 214.667 | 164.767 | **1,3×** | **no internar** |

   Una signatura LCC lleva dentro el autor y el año (`"GV1061.15.K39 A3 2006"`),
   así que es casi única: internarla no dedupe nada y, desde CPython 3.12, la
   vuelve inmortal — sube el suelo en vez de bajar el pico. **Quitado el
   `intern` de `lcc`**, conservado en `ddc` y en los códigos de idioma, y el
   docstring lleva ahora la tabla en vez de una afirmación sin respaldo.

## Un hallazgo nuevo del propio run medido (arreglado)

El run instrumentado **perdió la fase 3 a los 4 segundos** con
`httpcore.ConnectError: [Errno 104] Connection reset by peer`, justo después de
dos horas descargando editions. archive.org corta conexiones.

Doble lectura: (a) el diseño aguantó —la reanudabilidad por fases hizo que
recuperarse costara solo repetir la fase 3, no las dos horas anteriores—, pero
(b) un corte transitorio no debería exigir un dispatch manual.

`stream_dump_lines` reintenta ahora hasta 3 veces **mientras no haya entregado
ninguna línea**. La asimetría es el punto: abrir el stream es gratis de repetir,
pero un corte a media descarga **no** se reintenta, porque gzip no tiene punto
de rebobinado y releer desde arriba le daría al llamante los mismos millones de
líneas dos veces. Tres tests, uno por rama (reintenta y gana, no reintenta a
media lectura, agota el presupuesto y propaga).

## Lo que NO he tocado, y por qué

- **`SEED_TOP_N_BOOKS` en 100/10.000 frente a las 18.874 reales** (punto 4 no
  bloqueante de la review): sigue documentado en tres sitios y **sin cambiar**.
  Es una env var de Render y una decisión de producto del leader y del usuario,
  no mía. El reviewer coincide.
- **Nada de alcance nuevo**: ni el nocturno, ni el on-demand, ni el issue #26.
  `sync_books`, `search_book`, `get_book`, `_persist_book_authors` y
  `collect_book_authors` siguen sin aparecer en `git status`.

---

# Ronda 3 — respuesta a B4 (`progress/review_87.md`)

`bash init.sh` **verde: 1414 tests** (+2 sobre los 1412 de la ronda 2).

El reviewer tenía razón en todo, incluida la parte incómoda: **el test que yo
creía que sujetaba la asimetría del reintento no la sujetaba**. Lo verifiqué
mutando, no leyendo.

## Qué estaba mal, exactamente

`test_stream_dump_lines_does_not_retry_once_lines_have_been_handed_out`
simulaba el corte **truncando el cuerpo gzip**. Un gzip truncado lanza
`EOFError`, que **no** entraba en mi `except (httpx.TransportError,
httpx.HTTPStatusError)`: la excepción salía por encima del bloque de reintento
sin tocarlo. Su aserción era cierta por el **tipo de la excepción**, no por la
guarda — y por eso pasaba igual con la guarda borrada. El nombre prometía una
cosa y el test probaba otra.

## Lo que he hecho

### 1. El test que faltaba: un corte de transporte **de verdad** a media descarga

`test_stream_dump_lines_never_retries_after_handing_out_a_single_line`. Un
`MockTransport` cuyo cuerpo es un `SyncByteStream` que entrega bytes reales y
**después** lanza `httpx.ReadError` — que es literalmente lo que hizo
archive.org. Afirma las tres cosas pedidas: que la excepción se propaga, que el
transporte se abrió **una sola vez**, y que no hay ni una línea repetida.

**Detalle que costó y que dejo escrito en el propio test**: el fixture tiene que
estar dimensionado alrededor de `gzip.READ_BUFFER_SIZE` (128 KiB). `gzip` pide
ese buffer de bytes **comprimidos** antes de devolver un solo byte
descomprimido, así que un cuerpo cortado antes de eso no entrega ninguna línea
y el test sería **vacuo**: probaría la rama «murió sin producir nada», que es la
contraria. Mis dos primeros intentos (20 KB y 45 KB) fallaron exactamente por
ahí. El fixture son ahora 300.000 líneas cortadas a 4×`READ_BUFFER_SIZE`, y el
`_CHUNK_SIZE` del transporte se baja a 8 KiB por la misma razón en la capa de
httpx.

**Verificado por mutación**, las tres variantes:

| Mutación | Resultado |
|---|---|
| `if produced or attempt == ...` → `if attempt == ...` (reintentar a media descarga) | **2 tests en rojo** |
| borrar `produced += 1` | **2 tests en rojo** |
| sustituir el bucle por `yield from` (guarda entera fuera) | **2 tests en rojo** |

Antes las tres sobrevivían. Fichero restaurado y comprobado por `md5sum`.

### 2. Medido qué previene la guarda, sobre el mismo fixture del test

```
CON la guarda:  1 apertura · 170.960 líneas · 0 duplicados · propaga ReadError
SIN la guarda:  3 aperturas · 512.880 líneas · 341.920 DUPLICADOS
```

Coincide en forma con lo que midió el reviewer. Sobre las 56,7 M de líneas de
editions eso no es un test rojo: es `edition_count` inflado, el filtro de la
feature 73 dejando entrar obras que no debían y **un catálogo mal seleccionado
sin que se mueva ni un contador**. Es la clase de fallo invisible del issue #22.

### 3. `EOFError` entra en la cláusula — y digo por qué

El reviewer preguntaba si un gzip truncado debe tratarse como un corte de red.
**Sí**, y lo he hecho: `_RETRYABLE_STREAM_ERRORS` es ahora
`(httpx.TransportError, httpx.HTTPStatusError, EOFError, gzip.BadGzipFile)`.

Razón: un cuerpo que **se acaba antes de tiempo** es el mismo corte de conexión,
visto una capa más arriba (el descompresor en vez del socket). Antes se
comportaba distinto **por accidente** —se escapaba de la cláusula— y no por
decisión, y «por accidente» es exactamente lo que no quiero en el camino que
decide si se relee un dump de 12,59 GB.

La asimetría sigue mandando igual para todos: **si ya se entregó una línea, no
se reintenta**, venga el fallo del socket o del gzip. De hecho ahora es la
guarda —y no el tipo de la excepción— la que hace pasar el caso del gzip
truncado, que es justo lo que el reviewer echaba en falta.

### 4. El test cuyo nombre mentía

Renombrado a `test_stream_dump_lines_treats_a_truncated_body_the_same_way` y
reescrito para afirmar lo que de verdad pasa, ahora que la ruta es la misma:
entrega `["first", "second"]`, propaga `EOFError` y **abre el stream una sola
vez**. Se conserva —es un caso legítimo y distinto— pero ya no promete lo que
no hace.

### 5. Un tercer test, para que los otros dos no sean triviales

`test_stream_dump_lines_retries_a_body_that_dies_before_any_line`: el mismo
`ReadError`, pero **antes** de entregar nada, sí se reintenta y el run se salva.
Sin él, los dos tests anteriores pasarían también sobre un
`stream_dump_lines` que no reintentara nunca — que es una forma distinta de
estar roto.

## Lo que no he tocado

Nada más. Ni alcance nuevo, ni `SEED_TOP_N_BOOKS`, ni el nocturno, ni el
on-demand, ni el issue #26. El único fichero de producción tocado en esta ronda
es `backlogg/books/adapters/openlibrary_dump.py` (la tupla de excepciones y dos
docstrings); el resto son tests.

**Nota sobre la §7**: la medición de las fases 3 y 4 que tenía corriendo en
segundo plano se perdió al limpiarse el scratchpad entre sesiones. Los números
de las fases 1 y 2 —los que pedía B3, incluido el pico de 574 MB— están medidos
y siguen en pie; `docs/operations.md` sigue declarando los de las fases 3 y 4
como tiempo de una **pasada equivalente**, que es lo que son. No los presento
como algo que no son.
