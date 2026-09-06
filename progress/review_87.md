# Review — feature 87: `openlibrary_dump_seeding`

> **Este archivo tiene tres rondas.** El veredicto vigente es el de la
> **ronda 3**, al final: **APPROVED**. Los tres bloqueantes de la ronda 1
> (B1, B2, B3), el de la ronda 2 (B4) y los seis no bloqueantes están
> **cerrados y verificados por mutación**. Las rondas 1 y 2 se conservan tal
> cual como registro.

---

# Ronda 1 — CHANGES_REQUESTED (histórico)

**Veredicto:** CHANGES_REQUESTED

**Revisor:** agente reviewer · **Fecha:** 2026-09-04
**Rama:** `feat/openlibrary_dump_seeding` (todo el trabajo está sin commitear;
`git log main..HEAD` está vacío, así que el diff revisado es el working tree)

`bash init.sh` **verde, verificado por mí** (exit 0, 1398 tests). El rechazo no
va por ahí: va por dos huecos concretos de cobertura en la fase de escritura,
detallados en *Cambios requeridos*. El resto de la feature es sólido y lo he
comprobado, no leído.

---

## Checkpoints

- **C1** `bash init.sh` sin errores: **[x]** — ejecutado por mí, exit 0 (§ output abajo).
- **C2** sin `print()` de debug: **[x]** — `grep` sobre los 6 archivos nuevos: ninguno.
- **C3** sin TODOs sin contexto: **[x]** — ninguno en código; los hits de `\uXXXX` son texto de docstring.
- **C4** `ruff check` + `ruff format --check`: **[x]** — «All checks passed» / «308 files already formatted».
- **C5** todos los tests pasan: **[x]** — 1398 passed.
- **C6-C8** modelos y migraciones: **n/a** — la feature no toca el esquema. `git status alembic/` vacío, verificado.
- **C9-C13** endpoints: **n/a** — no se añade ninguno. `git status bruno/` vacío, verificado: correcto, no hay superficie HTTP nueva que sincronizar.
- **C14** fechas de APIs externas convertidas explícitamente: **[x]** — el año sale del dump como `int` y `book_to_dict` construye el `date`; `tests/test_openlibrary_dump_seeding.py:122` lo comprueba contra la DB real (`book.first_publish_date.year`). Mutar `min`→`max` en `merge_edition` mata 4 tests, o sea que la fecha está sujeta de verdad.
- **C15** ids externos únicos por test: **[x]** — comprobado con `grep`: los 9 OLIDs de obra y los 4 de autor del fixture no aparecen en ningún otro test de la suite. El fixture `db` aísla por transacción externa + savepoint.
- **C16-C17** fallback on-demand: **n/a** — no se toca (y eso es justo el criterio 8).
- **C18** sync idempotente: **[x]** — `test_seeding_twice_neither_duplicates_nor_loses` cuenta `Book`/`Person`/`Credit`/`ExternalId` antes y después de repetir la fase `load`.
- **C19** un error no aborta el resto: **[ ]** ← **Razón:** el informe lo da por heredado de `BatchWriter`, pero `BatchWriter` solo cubre el *fallo de escritura*. El mapeo previo (`build_item` → `book_to_dict`) está **fuera** de cualquier `try/except` en `scripts/seed_openlibrary_books.py:353`, al contrario que su gemelo `sync_books` (`backlogg/scheduler/jobs.py:809-838`), que envuelve exactamente ese paso y cuenta `errors += 1`. Una obra que reviente el mapeo aborta la fase entera y devuelve exit 1. Además no hay **ningún** test que ejercite el camino degradado.
- **C20** sin lógica de negocio en `routes.py`: **[x]** — n/a, no se toca ninguna ruta.
- **C21** sin queries SQLAlchemy en `service.py`: **[x]** — el adaptador `openlibrary_dump.py` no importa SQLAlchemy (verificado); la escritura pasa por `bulk_load_items` con el spec de `books/repository.py`.
- **C22** no se devuelven modelos ORM: **[x]** — n/a.

---

## Cambios requeridos (bloqueantes)

### B1 — Los tres contadores de la fase `load` no están sujetos por ningún test

`scripts/seed_openlibrary_books.py:364-372` publica `errors`, `people_errors` y
`skipped_links`. **Los tres se pueden poner a `0` a mano y los 1398 tests siguen
verdes.** Lo he comprobado mutando el código uno por uno:

| Mutación | Resultado |
|---|---|
| `"errors": writer.errors` → `"errors": 0` | **sobrevive** (76 passed) |
| `"people_errors": writer.people_errors` → `0` | **sobrevive** (76 passed) |
| `"skipped_links": link_skips.count` → `0` | **sobrevive** (76 passed) |

Por qué no los caza nada:

- `test_run_seeds_the_selected_catalog:100-101` afirma `errors == 0` y
  `skipped_links == 0` en el camino feliz. Un `0` constante satisface esas
  aserciones igual de bien que el contador real.
- `test_exit_code_is_two_when_the_catalog_is_incomplete:273-284` prueba el
  predicado `_exit_code` con dicts escritos a mano. Prueba la fórmula, **no el
  cableado** `writer.errors → summary → _exit_code`.

Por qué importa: esos tres números y el exit code 2 son el **único** canal de
información de un run desatendido de 1-2 h en Actions, y este proyecto ya se
quemó exactamente ahí (issue #22, cerrado hace días precisamente para que
`skipped_links` dejara de ser invisible en la siembra). Si un contador se
desconecta, la siembra se hace a ciegas y el run se reporta verde con catálogo
parcial — que es literalmente lo que el docstring del script (líneas 51-54)
promete que no puede pasar.

**Qué falta:** al menos un test que provoque un run *degradado* de verdad y
compruebe que el número llega al `summary` y que `main()` devuelve 2. El patrón
ya existe en el repo para el nocturno:
`tests/test_sync_genre_slug_collision.py::test_sync_movies_bad_item_does_not_block_slice`
(upsert envenenado) y `tests/shared/test_link_skip_observability.py::test_sync_games_reports_the_links_it_could_not_write`
(colisión real de terna `(item_type, source, external_id)`). Aplicar uno de los
dos a `phase_load` cierra B1 y B2 a la vez.

### B2 — El mapeo por ítem de `phase_load` no está protegido, al revés que `sync_books`

`scripts/seed_openlibrary_books.py:353` — `item = build_item(...)` está desnudo
dentro del bucle. `sync_books` hace lo mismo dentro de un `try/except` que
cuenta `errors += 1` y sigue (`backlogg/scheduler/jobs.py:809-838`), y su
comentario explica por qué (el `search_doc` montado a mano es frágil, issue
#17). El camino de dumps parte de 17,5 GB de datos de terceros y el propio
módulo invoca ese argumento tres veces (`openlibrary_dump.py:253-255`,
`484-489`) para justificar por qué los parsers toleran una línea mala — pero la
tolerancia se pierde justo en el último paso, el que escribe.

Hoy `book_to_dict` es defensivo y probablemente no lanza, así que esto no es un
bug demostrado: es una regresión de robustez respecto al código del que se
declara hermano, y es la razón de que C19 quede en `[ ]`. Va junto con B1
porque el mismo test lo cierra.

### B3 — `progress/impl_87.md` §7 es un marcador de posición vacío, y §4.3 apunta a él

`progress/impl_87.md:223-226`: la sección «Coste real del run (medido, no
estimado)» no tiene contenido. Y `progress/impl_87.md:180-182` remite a esa
sección para el dato del pico de memoria de la fase 2 («ver §7»). Resultado: el
informe promete un número que no está ni en §7 ni en `docs/operations.md` (cuya
sección «Memoria» describe la cota de forma cualitativa, sin cifra). El único
número de memoria del repo es el «444 MB de RSS, measured» del docstring de
`count_reading_log` (`openlibrary_dump.py:328-329`), que es de la **fase 1**, no
de la 2. O se rellena §7, o se quita la sección y la referencia cruzada.

Aclaración: el **criterio 7** de aceptación pide tiempo y disco, y eso **sí**
está documentado y es correcto (`docs/operations.md`, tabla por fase). B3 es
integridad del informe, no incumplimiento del criterio.

---

## No bloqueante (para la siguiente iteración o para el leader)

1. **`aggregate_editions` — la guarda interna de whitelist no está probada.**
   `openlibrary_dump.py:508-510`: borrar el `if work_id not in wanted: continue`
   deja los 76 tests verdes. El fixture no tiene ninguna edición cuyo `works[]`
   apunte a la vez dentro y fuera de la whitelist, así que solo se ejercita el
   pre-filtro por regex (línea 503). El código es correcto; lo que falta es una
   línea de fixture con dos obras en `works[]`. Es la guarda que acota la
   memoria de la pasada de 12,59 GB, o sea que merece estar clavada.
2. **`select_works` es código de producción que solo usan los tests.**
   `openlibrary_dump.py:586` no lo llama nadie en `scripts/`: `phase_editions`
   (líneas 196-213) reimplementa el bucle. O sea que el test del criterio 4
   (`test_openlibrary_dump_fixture.py:36`) valida una copia y el script corre la
   otra. El filtro real (`select_language`) sí es compartido, así que la deriva
   posible se limita al orden y al default de `counts.get`, pero la duplicación
   es evitable: que `phase_editions` llame a `select_works`.
3. **Otras cuatro mutaciones supervivientes**, todas menores: quitar la guarda de
   `untitled` (script:330-331), ignorar `--phase` (script:387-388), no llamar
   nunca a `refresh_catalog_search` (script:360) y no pasar el `work_detail` a
   `book_to_dict` (script:329, es decir, sembrar sin sinopsis) no rompen ningún
   test. La última contradice el §3.3 bis del informe, que presenta el
   `overview` como mejora deliberada: está probada en el adaptador, no en la
   escritura (nadie afirma `book.overview` en la DB).
4. **Criterio 3 cumplido a medias, y bien señalado.** El comentario falso de
   `config.py` está corregido y la incoherencia documentada en tres sitios,
   pero `SEED_TOP_N_BOOKS` sigue en `100` por defecto (`config.py:36`) y en
   10.000 en Render, ambos por debajo de las 18.874 que el filtro entrega. Es
   inerte para la siembra, **no** para `sync_books`, que sí sigue vivo (criterio
   8). El implementer hizo lo correcto al no tocar una env var de Render por su
   cuenta: **queda como decisión pendiente del leader/usuario**, no como fallo
   del implementer.
5. **Caché de Actions: `restore-keys` con prefijo puede resucitar un work-dir de
   otro mes.** `.github/workflows/backfill-sync.yml`: la clave lleva
   `github.run_id` (única) pero `restore-keys: openlibrary-seed-workdir-`
   restaura la más reciente que empiece por ahí. Un `mode=dump` sin
   `force_phase` lanzado con una caché anterior aún viva salta las cuatro fases
   y resiembra el catálogo del dump viejo, en silencio. La expiración de 7 días
   de Actions lo tapa casi siempre, y `-f force_phase=true` lo resuelve, pero la
   invocación que `docs/operations.md` documenta como la normal
   (`gh workflow run ... -f mode=dump`) es justo la que cae en la trampa. Vale
   una línea de aviso en `docs/operations.md`.
6. **`docs/architecture.md:65-69`** lista los tres scripts del repo y no se ha
   añadido `seed_openlibrary_books.py`. Drift de una línea.
7. **`sys.intern` sobre `ddc`/`lcc`: la afirmación no es verificable y es
   discutible.** `openlibrary_dump.py:428-431` dice que internar es «the
   cheapest lever on the peak memory of the 12,59 GB pass». Desde CPython 3.12
   las cadenas internadas son inmortales (y el entorno corre 3.14.7), así que
   internar signaturas LCC de cardinalidad casi única (`"GV1061.15.K39 A3 2006"`)
   sube el suelo de memoria en vez de bajar el pico. Para los códigos de idioma
   (línea 444) el interning es claramente correcto. Ni confirmo ni desmiento el
   efecto neto: **no es medible desde el repo**.

---

## Lo que he verificado yo, y cómo

### 1. La frontera de alcance: confirmada mecánicamente

Reconstruí `jobs.py` de `HEAD` aplicándole el `sed` del renombrado y lo comparé
con la versión de la rama. **La única diferencia son 6 líneas de docstring
añadidas a `BatchWriter`.** Cero cambios de comportamiento. El mismo
procedimiento sobre los 9 archivos de test: **diferencia vacía en los 9**, o
sea puramente mecánico. `books/service.py`, `books/adapters/open_library.py` y
`books/routes.py` ni aparecen en `git status`: `sync_books`, `search_book`,
`get_book`, `_persist_book_authors` y `collect_book_authors` están intactos.
Criterio 8: cumplido.

### 2. Los tests prueban, no acompañan: 27 de 29 mutaciones muertas

Muté el código y ejecuté los tres módulos nuevos. Muertas (con el test que
debería fallar, fallando):

`edition_count += 2` · unión de idiomas rota · `int()` en vez de `math.ceil()` ·
un `number_of_pages` de 0 dejando de votar · los tres umbrales `>=` → `>` ·
`ddc`/`lcc`/`subject_facet` vaciados en el search doc · el regex de año con
`\b` en vez de la guarda de dígitos · `min` → `max` en `first_publish_year` ·
`min` → `max` en el suelo de whitelist · contar solo la balda «Want to Read» ·
la rama ES evaluada antes que la EN (o sea, perder el `NOT language:eng`) ·
`role="AUTHOR"` → otro rol · el fallback de slug del issue #18 · escritura
atómica → escritura directa · salto de fase desactivado · `--force` ignorado ·
`people=[]` en el `BulkItem` · `external_id` alterado · preferencia de portada
invertida · `build_work_detail` devolviendo `None` · `isbn` no propagado.

Supervivientes: los 4 de B1 y del punto 3 no bloqueante, más la guarda interna
de whitelist (punto 1). **Restaurado el código y verificados los md5 contra la
copia previa: idénticos.** El working tree quedó como lo encontré.

Las dos correcciones del §8 del informe existen y están clavadas:
`math.ceil(statistics.median(...))` en `openlibrary_dump.py:379` con
`test_pages_median_follows_open_librarys_own_rule` (mata tanto `int()` como
«el 0 no vota»), y `_YEAR_RE = r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)"` en la
línea 135 con 15 casos parametrizados; cambiarlo por `\b` mata
`test_publish_year_extraction[c1985-1985]` y solo ese, que es el que debe.

### 3. El criterio 4, reproducido a mano

Corrí el pipeline del dump sobre el fixture y lo comparé con `search_docs.json`
yo mismo. Los números del §4.2 del informe **salen exactos**:

- `edition_count` 13/12/11/11/2 == Solr; `number_of_pages_median`
  398/851/364/295/205 == Solr; `first_publish_year` y la unión de idiomas ==
  Solr en las cinco obras.
- Los géneros del dump == los de `search.json` en las cuatro seleccionadas,
  partiendo de notación **cruda** (`813/.6`, `PS3608.A98845L68`,
  `GV697.G6G6 2018`) contra la normalizada de Solr (`813.6`,
  `PS-3608.00000000.A98845L68`). Ese es el punto que el plan pedía demostrar y
  está demostrado.
- `subjects` == `subject_facet` en las cinco (14/14, 27/27, 7/7, 13/13, 0/0),
  tal como afirma el §3.3.

El test compara contra el doc de `search.json`, nunca contra literales:
confirmado leyendo `test_openlibrary_dump_fixture.py` entero.

### 4. Streaming: sin disco y con memoria acotada

`stream_dump_lines` (`openlibrary_dump.py:214-226`) es `httpx.stream` →
`_ChunkReader` (un `RawIOBase` sobre el iterador de chunks) → `GzipFile` →
`TextIOWrapper`. **Ningún byte de dump toca el disco**, confirmado leyendo el
camino completo: no hay ni un `open(...,"wb")` ni un `tempfile` en todo el
módulo. Las únicas estructuras vivas son el `Counter` de la fase 1 (~3,3 M
obras con estantería, proporcional al reading-log de 0,12 GB, no al corpus) y el
dict de agregados acotado por la whitelist. Nada proporcional a las 41,6 M de
obras ni a las 56,7 M de ediciones. Criterio 1: cumplido.

Matiz menor: `test_stream_dump_lines_decompresses_the_response_on_the_fly` usa
`httpx.MockTransport` con el cuerpo entero en memoria, así que prueba la
descompresión al vuelo y la ausencia de disco, pero no el troceado. No lo cuento
en contra: probar la cota de memoria de verdad exige el dump real.

### 5. Reanudabilidad

Escritura atómica real (`.tmp` + `os.replace`, script:121-135), salto de fase
por artefacto (script:386-397) y fase 5 idempotente por upsert. Los tres tienen
test y los tres tests **pueden fallar**: verificado matando cada mecanismo por
separado. `test_a_phase_with_an_artifact_is_skipped` usa un stream que revienta
al tocarlo, que es la forma correcta de probarlo. Criterio 6: cumplido.

### 6. El fixture: el README dice la verdad

Comprobado punto por punto contra los ficheros:

- Las ediciones por obra son 13/12/11/11/2 + 2 de relleno apuntando fuera de la
  whitelist = 51 líneas. Coincide con lo que el README afirma y con los
  `edition_count` de Solr.
- El reading-log tiene 25/25/25/25 truncadas, `OL8960135W` con sus 19 completas
  y las cuatro obras de contorno con 4, 5, 19 y 20. Exactamente lo declarado.
- `authors.tsv` tiene 4 autores y **falta** `OL2144245A`, el caso de degradación
  declarado.
- Los 5 formatos de columna son los declarados (5 columnas los tres TSV de
  registro, 4 el reading-log).

Sobre la **procedencia**, que es lo que se me pidió mirar con lupa: el README
afirma que son líneas verbatim del dump `2026-08-31` recorrido en streaming, y
**no** presenta nada como reconstruido desde la API. Todo lo que puedo
contrastar lo respalda: (a) las filas de reading-log —con `edition_key`, balda y
fecha por fila— **no existen en ninguna API pública** de Open Library, solo en
el dump, así que ese fichero solo puede venir de ahí; (b) verifiqué en vivo
`search.json` para `OL8960135W` y el doc coincide **campo a campo** con
`search_docs.json`, incluidos el orden de los 6 `lcc` y el `readinglog_count`
de 19, y los campos presentes son `_OL_SEARCH_FIELDS` más los del filtro de la
feature 73, tal como declara. **Lo que no puedo verificar** y digo en vez de dar
por bueno: no he re-descargado los 17,5 GB para comparar byte a byte las líneas
de `works`/`editions`/`authors`; la API sirve el mismo documento que el dump, así
que esas tres no son distinguibles por su contenido.

Y ningún test toca la red: además de la inspección estática, corrí los 76 tests
con `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` apuntando a un puerto muerto —
**76 passed en 0,57 s**. Criterio 10: cumplido.

### 7. Documentación vs. código

`docs/external-apis.md`, `docs/seeding-plan.md`, `docs/operations.md` y
`config.py` cuentan la misma historia y coinciden con lo que el código hace: la
tabla campo→origen, el formato de 4 vs 5 columnas, el umbral de whitelist como
`min` de los dos suelos, `ceil` de la mediana con el `0` votando, el `min` de
años. La línea falsa «Rate limits: none enforced» está corregida y la afirmación
previa —el repo ya decía que «books usa dumps de Open Library» sin que fuera
verdad— ahora es cierta y está marcada como tal en el sitio donde estaba mal
(`docs/operations.md`, modo `enumerate`). Criterios 2 y 9: cumplidos.

**Lo que no es verificable desde el repo** y por tanto no doy por bueno: los
tamaños de dump en GB, los recuentos de líneas (12.838.026 / 56.728.501 /
41.591.088 / 15.412.139), la distribución de `readinglog_count`, los tiempos por
fase (61 s / 35-100 min / ~14 min / ~3 min), el ancho de banda de 6,25 MB/s y la
tabla dump-vs-Solr de las obras grandes. Son mediciones contra fuentes externas
de 17,5 GB. Lo que **sí** verifiqué en vivo, y cuadra, es el `readinglog_count`
de 19 de `OL8960135W`. El propio §4.3 del informe es honesto sobre lo que asumió;
señalo además que `docs/operations.md` presenta el tiempo de la fase 2 como
medido (lo que exige una pasada completa) pero no reporta el número de obras
seleccionadas que esa pasada produce, y sigue diciendo «~19 k» anclado en el
`numFound` de Solr.

---

## output de `bash init.sh`

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
308 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
........................................................................ [  5%]
[... 19 líneas de puntos recortadas ...]
..............................                                           [100%]
1398 passed in 31.90s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
EXIT=0
```

El `warning` de `tool.uv.dev-dependencies` es previo a esta rama.

---

## Resumen para el leader

La feature está bien hecha y la parte difícil está bien probada: la frontera de
alcance es limpia y verificada mecánicamente, el test del criterio 4 compara
contra el oráculo correcto y sus 21 aserciones muerden, el streaming no toca
disco, la reanudabilidad es real y el fixture es honesto. Lo que falta es
pequeño y está localizado en un sitio: **la fase 5 no tiene ni un test del
camino degradado**, y por eso sus tres contadores pueden desconectarse sin que
nada chille. Un solo test —del patrón que el repo ya tiene para el nocturno—
cierra B1, B2 y C19 a la vez. B3 es borrar o rellenar una sección del informe.


---

# Ronda 2 — respuesta a la ronda 1 (histórico)

**Veredicto:** CHANGES_REQUESTED
**Fecha:** 2026-09-06 · **Rama:** `feat/openlibrary_dump_seeding` (sigue sin commitear)

`bash init.sh` **verde, verificado por mí**: exit 0, **1412 passed** (+14 sobre
los 1398 de la ronda 1). Output al final.

**Los tres bloqueantes de la ronda 1 están cerrados de verdad, y los seis no
bloqueantes también.** Lo he comprobado repitiendo el método: volví a mutar el
código, mutación por mutación, sobre los 90 tests de los tres módulos.

Rechazo por **una sola cosa, nueva**: el reintento que el implementer añadió a
`stream_dump_lines` está **bien implementado pero no lo sujeta ningún test en la
rama que importa**. Es un bloqueante de una prueba, no de un rediseño.

---

## B4 (NUEVO, bloqueante) — La asimetría del reintento no tiene test

`backlogg/books/adapters/openlibrary_dump.py:242-262`. La lógica es correcta —
lo verifiqué empíricamente, no leyéndola— pero **se puede borrar la guarda y los
1412 tests siguen verdes**:

| Mutación | Resultado |
|---|---|
| `if produced or attempt == _DUMP_CONNECT_ATTEMPTS:` → `if attempt == _DUMP_CONNECT_ATTEMPTS:` (o sea: **reintentar también a media descarga**) | **sobrevive**, 90 passed |
| borrar `produced += 1` (mismo efecto) | **sobrevive**, 90 passed |

### Por qué el test que debería cazarlo no lo caza

`test_stream_dump_lines_does_not_retry_once_lines_have_been_handed_out`
(`tests/books/test_openlibrary_dump.py`) simula el corte a media descarga
**truncando el cuerpo gzip**. Lo ejecuté y comprobé qué excepción sale:

```
TRUNCATED-GZIP test raises: EOFError
  is httpx.TransportError?  False
  is httpx.HTTPStatusError? False
  -> ¿lo captura el except del reintento? NO
```

Un gzip truncado lanza `EOFError`, que **no lo captura la cláusula
`except (httpx.TransportError, httpx.HTTPStatusError)`**. El bloque de reintento
no llega a consultarse nunca. Su aserción —`assert not isinstance(raised.value,
httpx.TransportError)`— es cierta por el tipo de la excepción, no por la guarda,
y **pasa igual con la guarda borrada**. El test prueba «un gzip truncado
propaga», que es verdad y es otra cosa.

La rama real —un `TransportError` **después** de haber entregado líneas, que es
exactamente lo que hace archive.org al cortar a la media hora— no la construye
ningún test.

### Qué previene la guarda, medido

Monté el escenario real (cuerpo gzip de 9,5 MB comprimido, > `_CHUNK_SIZE`, con
`httpx.ReadError` al 80 %):

```
WITH the guard (tal como se entrega):
  transport opens : 1
  lines delivered : 226.821
  DUPLICATES      : 0
  raised          : ReadError          <- correcto: propaga, la fase se repite

WITHOUT the guard (mutación aplicada):
  transport opens : 3
  lines delivered : 680.421
  distinct lines  : 226.807
  DUPLICATES      : 453.614            <- el llamante recibe el dump 3 veces
```

Sobre los 56,7 M de líneas de editions eso no es un test rojo: es
`edition_count` multiplicado, `readinglog_count` multiplicado, el filtro de la
feature 73 admitiendo obras que no debían entrar y un catálogo **silenciosamente
mal seleccionado**. Ningún contador del panel (`errors`, `people_errors`,
`skipped_links`) se movería: los tres subirían tan campantes con el dump leído
tres veces. Es justo la clase de fallo invisible por la que este proyecto montó
el issue #22.

**Por qué bloqueo:** es el mismo listón que apliqué en la ronda 1 con los tres
contadores —código correcto, cero cobertura, se borra y nadie se entera— y el
informe afirma en su §«hallazgo nuevo» que tiene **«tres tests, uno por rama»**.
No los tiene: tiene dos que muerden (`retries_a_connection_lost_before_any_data`
y `gives_up_after_the_attempt_budget`, ambos muertos por mutación, ver abajo) y
uno que no ejercita la rama que dice ejercitar.

**Qué falta exactamente** (una prueba): un `MockTransport` cuyo
`SyncByteStream` entregue bytes suficientes para que salgan líneas y **después**
lance `httpx.ReadError`, y afirmar (a) que se propaga, (b) que el transporte se
abrió **una sola vez** y (c) que no hay líneas repetidas. El `assert calls["n"]
== 1` es la mitad que de verdad clava la asimetría. Con eso, borrar la guarda
pone el test en rojo.

---

## Lo que sí quedó cerrado, verificado por mutación

**Los tres contadores (B1): cerrados.** En la ronda 1 las tres mutaciones
sobrevivían; ahora **cada una mata su test**:

| Mutación | Ronda 1 | Ronda 2 | Test que la mata |
|---|---|---|---|
| `"errors"` → `0` | sobrevivía | **KILLED** | `test_a_work_that_cannot_be_mapped_costs_only_that_work` |
| `"people_errors"` → `0` | sobrevivía | **KILLED** | `test_a_rejected_credit_is_counted_and_never_costs_the_book` |
| `"skipped_links"` → `0` | sobrevivía | **KILLED** | `test_an_external_id_that_cannot_be_linked_is_reported` |
| `mapping_errors` no sumado a `errors` | — | **KILLED** | el de la obra envenenada |

Y los tests son honestos, no decorativos: leí los tres. Cada uno provoca una
degradación **real** contra la DB de test y afirma además lo que *no* se pierde
(`synced == 3` con la obra envenenada, `synced == 4` con los credits caídos, la
fila vieja conservando el id en el caso del issue #22). El de `skipped_links`
reproduce la forma real del #22 —una fila anterior que ya posee la terna— y no
un mock. `test_main_turns_a_degraded_summary_into_exit_2` cierra el último
eslabón pasando por `main()`.

**B2: cerrado.** `build_item` va dentro de `try/except` en
`scripts/seed_openlibrary_books.py`, cuenta `mapping_errors`, sigue, y lo suma a
`errors` del summary — el patrón de `sync_books` (`jobs.py:809-838`). Las dos
mutaciones lo confirman: quitar el `try/except` (**KILLED**) y tragarse el error
sin contarlo (**KILLED**). **C19 pasa a `[x]`.**

**B3: cerrado.** La §7 existe y tiene la tabla del run instrumentado; las dos
referencias cruzadas del §4.3 ya no cuelgan (están tachadas y resueltas).
**Marcado como pedía el leader:** los números de esa sección —574 MB de pico de
RSS, 7.516 s de la fase 2, 19.221 obras elegidas, 3,1 MB de disco, 392.466 obras
con edición— **no son verificables desde el repo**. Son un run de dos horas
contra archive.org. No los pongo en duda —son coherentes entre sí, con
`docs/operations.md` y con la cota de memoria que sí puedo razonar— pero los
doy por *declarados*, no por comprobados. Lo que sí verifiqué en la ronda 1 y
sigue valiendo es la mitad medible del criterio 4: el fragmento reproduce
exactamente los agregados y los géneros de `search.json`. El +1,8 % de 19.221
sobre 18.874 es el contraste a escala y es una afirmación del implementer.

**Los seis no bloqueantes: cerrados.** Todos verificados por mutación
(**KILLED** los cinco que tocaba, más dos comprobados leyendo):

1. Guarda interna de whitelist → `test_aggregate_editions_drops_the_works_of_a_shared_edition_that_are_not_wanted`.
2. `select_works` → `phase_editions` **ahora lo llama** (leído: la copia del bucle ya no está, y el comentario dice por qué). Se acabó el riesgo de que el test del criterio 4 valide una función que el script no corre.
3. `untitled`, `--phase`, `refresh_catalog_search` y el `overview` en la fila de la DB → un test cada uno, los cuatro **KILLED**.
4. Trampa de la caché de Actions → **arreglada, no solo avisada**: el `restore` está condicionado a `resume == 'true'`, así que un `mode=dump` normal empieza siempre del dump del mes en curso y no puede resucitar un catálogo viejo en silencio. El `save` sigue incondicional (`always()`), que es lo que hay que hacer. Correcto.
5. `docs/architecture.md` → script añadido.
6. `sys.intern` → medido y corregido: `intern` fuera de `lcc`, dentro de `ddc` y de los idiomas, con la tabla de ratios en el docstring en vez de una afirmación sin respaldo. La decisión es la correcta (1,3× no justifica inmortalizar una cadena). La tabla en sí (59.482/216, 115.934/10.717, 214.667/164.767) **no es verificable desde el repo**.

**Sobre la línea sintética del test de whitelist — mi criterio, ya que se me
pide:** el trade-off es **el correcto**, y lo firmo. La afirmación «verbatim» del
README del fixture es una propiedad que sostiene todo el valor del fragmento
—lo que se está probando es el *formato*—, y meterle una línea fabricada la
habría falseado para clavar una guarda. Ponerla inline en el test unitario, que
es un fichero donde los dicts inline ya son la norma, conserva las dos cosas. El
docstring declara que es sintética y por qué, que es lo que hace legítima la
decisión. Verifiqué además su premisa en la mitad que sí puedo: **0 de las 51
ediciones del fixture nombran más de una obra**, así que el caso efectivamente
no se puede tomar del fragmento. Que tampoco aparezca en las 6.430 líneas que
muestreó no lo puedo comprobar, y él tampoco afirma más de lo que vio.

**Regresión: nada de lo que ya funcionaba se ha roto.** Reejecuté 10 mutaciones
de la ronda 1 (`ceil` vs `int`, el `0` que vota, el regex del año con `\b`,
`edition_count`, `ddc`/`lcc`/`subject_facet` vaciados, escritura atómica, salto
de fase): **las 10 siguen muertas**. Y la frontera de alcance sigue intacta:
`jobs.py` comparado contra `HEAD` con el `sed` del renombrado aplicado sigue
dando **solo las 6 líneas de docstring de `BatchWriter`**; `backlogg/books/`
no tiene más cambio que el fichero nuevo del adaptador.

---

## No bloqueante (ronda 2)

1. **`response.raise_for_status()` se puede borrar y no falla nada**
   (`openlibrary_dump.py:246`; mutación sobrevive). Un 404 o un 503 devolverían
   un cuerpo de error a `gzip`, que reventaría con un error peor de leer. Un
   test de «un 500 acaba propagando» lo cerraría.
2. **Reintentar `HTTPStatusError` es discutible y no está probado**
   (mutación «quitar `HTTPStatusError` del `except`» sobrevive). Un 404 —nombre
   de dump mal escrito— se reintenta 3 veces con 5 s y 10 s de espera antes de
   fallar. Inofensivo, pero son 15 s y un log confuso por un error que no es
   transitorio. Separar 5xx/429 de 4xx sería más honesto.
3. **`_CHUNK_SIZE = 1 << 20` interactúa con la guarda de forma no documentada.**
   Lo descubrí montando la prueba de B4: `iter_bytes(1 MiB)` no entrega nada
   hasta acumular un megabyte **comprimido**, así que un corte dentro del primer
   MB deja `produced == 0` y **sí** se reintenta — que es correcto y deseable,
   pero es una propiedad emergente del tamaño de chunk, no algo que el docstring
   diga. Una línea lo dejaría claro.
4. **`SEED_TOP_N_BOOKS`** sigue en 100/10.000 frente a las 18.874 (ahora 19.221)
   reales. Sin cambios y bien documentado en tres sitios. Coincido con el
   implementer: es una env var de Render y una **decisión del leader y del
   usuario**, no del implementer ni mía.

---

## Checkpoints (ronda 2)

- **C1** `init.sh` sin errores: **[x]** — exit 0, verificado por mí.
- **C2** sin `print()` de debug: **[x]**
- **C3** sin TODOs sin contexto: **[x]**
- **C4** `ruff check` + `format --check`: **[x]** — «All checks passed» / «308 files already formatted».
- **C5** todos los tests pasan: **[x]** — 1412 passed.
- **C6-C8** modelos y migraciones: **n/a** — no se toca el esquema.
- **C9-C13** endpoints: **n/a** — ninguno nuevo; `bruno/` sigue sin cambios.
- **C14** fechas convertidas explícitamente: **[x]**
- **C15** ids externos únicos por test: **[x]** — la fila `stale` del test de `skipped_links` usa un slug propio y el fixture `db` revierte por test.
- **C16-C17** fallback on-demand: **n/a**
- **C18** sync idempotente: **[x]**
- **C19** un error no aborta el resto: **[x]** ← **resuelto en la ronda 2**: `build_item` en `try/except`, contado y sujeto por dos mutaciones.
- **C20-C22** separación de capas: **[x]**

Ningún checkpoint en `[ ]`. **El rechazo no viene de los checkpoints, viene de
B4**: la regla del proyecto es que un checkpoint en `[ ]` impide aprobar, no que
tenerlos todos en `[x]` obligue a aprobar.

---

## output de `bash init.sh` (ronda 2)

```
── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (87 features)

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
308 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
1412 passed in 30.92s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
EXIT=0
```

(Recortadas las secciones 1-2 y las líneas de puntos de pytest. El `warning` de
`tool.uv.dev-dependencies` es previo a esta rama.)

---

## Resumen para el leader

La ronda 2 es un buen trabajo: los tres bloqueantes están cerrados **de verdad**
—lo he comprobado mutando, no leyendo el informe— y los tests nuevos de run
degradado son de los que muerden. La trampa de la caché la arregló en vez de
documentarla, y en `sys.intern` midió antes de decidir.

Queda **una** cosa, y es de la ronda 2, no de la 1: el reintento nuevo de
`stream_dump_lines` está bien pensado y bien implementado —lo verifiqué con un
experimento, no de palabra— pero su rama crítica no la sujeta ningún test, y el
test que dice sujetarla ejercita otro camino (`EOFError`, que el `except` ni
captura). Borrar esa guarda deja los 1412 tests verdes y mete 453.614 líneas
duplicadas por cada corte de archive.org, sin que ningún contador se entere.

**Es una prueba de trabajo**, y está especificada arriba línea a línea. Si el
leader prefiere aceptar el riesgo y mergear, que sea una decisión consciente y
suya: el código que se entrega hoy es correcto, lo que falta es la red que
impida que deje de serlo mañana. Yo, como revisor, no puedo firmarlo con esa
rama a cero.


---

# Ronda 3 — veredicto final

**Veredicto:** APPROVED
**Fecha:** 2026-09-06 · **Rama:** `feat/openlibrary_dump_seeding`

`bash init.sh` **verde, verificado por mí**: exit 0, **1414 passed** (+2 sobre
los 1412 de la ronda 2). Output al final.

**B4 está cerrado.** Verificado por mutación, no por lectura del informe. Y la
decisión de diseño que trajo consigo —meter `EOFError`/`BadGzipFile` en la
cláusula de reintento— la he auditado por separado: es correcta y no abre
ninguna puerta que importe.

Superficie tocada esta ronda: **un solo archivo de producción**, confirmado con
`diff` contra mi copia de la ronda 2 — `openlibrary_dump.py`, y dentro de él
solo la tupla `_RETRYABLE_STREAM_ERRORS` y dos docstrings.
`scripts/seed_openlibrary_books.py` **byte a byte idéntico**. El fixture, sin
tocar (228 líneas). No he vuelto a auditar lo cerrado en la ronda 2.

---

## B4 — cerrado

Las dos mutaciones que **sobrevivían** en la ronda 2 ahora **matan dos tests cada una**:

| Mutación | Ronda 2 | Ronda 3 | Tests que caen |
|---|---|---|---|
| `if produced or attempt == …` → `if attempt == …` (reintentar también a media descarga) | **sobrevivía** | **KILLED** | `…never_retries_after_handing_out_a_single_line`, `…treats_a_truncated_body_the_same_way` |
| borrar `produced += 1` | **sobrevivía** | **KILLED** | las mismas dos |
| `if True:` (no reintentar nunca) | KILLED | **KILLED** (3 tests) | + `…retries_a_body_that_dies_before_any_line` |
| `_DUMP_CONNECT_ATTEMPTS = 3 → 1` | KILLED | **KILLED** (2 tests) | los dos de reintento |
| quitar `httpx.TransportError` de la tupla | KILLED | **KILLED** (3 tests) | |

Coincide con lo que midió el leader antes de pasármelo, y con el mismo md5
(`51ac8b70e41ff716320e7bf121226bf4`).

### El test nuevo no es vacuo — comprobado, no asumido

Era la pregunta correcta, porque el fallo del test de la ronda 2 fue exactamente
ese. Repliqué el cuerpo de
`test_stream_dump_lines_never_retries_after_handing_out_a_single_line` e
instrumenté lo que el llamante recibe de verdad:

```
body 697.849 B, cut 524.288 B (75,1 % del cuerpo)
  lines received : 170.960      <- entrega líneas antes del corte
  distinct       : 170.960   duplicates: 0
  transport opens: 1
  raised         : ReadError
  first / last   : 'line 0' .. 'line 170959'
```

Afirma las tres cosas que pedí: propagación, **una sola apertura** y ausencia de
repetidos. Y lleva algo mejor que el dimensionado: la línea

```python
assert received, "the body must hand out lines before the cut, or this proves nothing"
```

es un **seguro anti-vacuidad**. Si alguien toca `_CUT_OFF_AT`, `_CHUNK_SIZE` o
la versión de `gzip` y el cuerpo deja de entregar líneas, el test se pone rojo en
vez de volverse decorativo en silencio — que es justo cómo el test original pasó
inadvertido. El dimensionado alrededor de `gzip.READ_BUFFER_SIZE` (128 KiB) está
explicado en el propio módulo y es correcto: el `assert len(body) > cut_at` del
helper cierra el otro extremo.

### El test que mentía, y el tercero

- `test_stream_dump_lines_treats_a_truncated_body_the_same_way`: el nombre ya
  describe lo que hace. Y ahora **muerde**: afirma `received == ["first",
  "second"]` y `calls["n"] == 1`, o sea que hubo entrega y no hubo reapertura.
  Cae con las mutaciones A1/A2.
- `test_stream_dump_lines_retries_a_body_that_dies_before_any_line`: existe y
  cubre la rama simétrica a nivel de *lectura* (no solo de conexión, que ya
  cubría el test previo). Sin él, la mutación «no reintentar nunca» seguiría
  cazándose, pero con menos precisión: ahora caen 3 tests en vez de 2, y uno
  nombra exactamente la rama.

---

## La decisión sobre `EOFError`: la juzgo correcta

Es el punto que pedía criterio, así que lo auditué por separado, probando el
comportamiento **por forma de fallo**:

| Forma del fallo | Aperturas | Líneas entregadas | Excepción | Reintenta |
|---|---|---|---|---|
| Página HTML de error servida con 200 (`BadGzipFile` en el byte 0) | 3 | 0 | `BadGzipFile` | **sí** |
| Cuerpo truncado antes de la primera línea | 3 | 0 | `EOFError` | **sí** |
| Cuerpo truncado **después** de entregar líneas | **1** | 2 | `EOFError` | **no** |
| Deflate corrupto a mitad de miembro | **1** | 0 | `zlib.error` | **no** (no está en la tupla) |
| Fallo de CRC al cerrar el miembro | **1** | 20.000 | `BadGzipFile` | **no** |

De aquí salen las tres cosas que importan:

1. **Ninguna forma produce duplicados.** Todo lo que se reintenta tiene
   `produced == 0` por construcción de la guarda, así que la duplicación es
   imposible por diseño, no por suerte. Es exactamente la mejora que pedía la
   ronda 2: el caso del gzip truncado pasaba antes **por el tipo de excepción**
   (se escapaba del `except`) y ahora pasa **por la regla**.
2. **La puerta del `.gz` corrupto de verdad está acotada.** Solo se reintenta si
   la corrupción está al principio; cuesta 3 intentos con backoff de 5 s y 10 s
   = **15 segundos** antes de fallar duro, sobre un run de 1-2,5 h. Y termina
   siempre: el presupuesto es fijo y está probado
   (`…gives_up_after_the_attempt_budget`). No es un problema.
3. **La corrupción a media descarga falla rápido**, porque `zlib.error` no está
   en la tupla. Errar hacia «no reintentar» es el lado correcto en el que errar.

Detalle menor y honesto: la tupla no es exhaustiva sobre «la descarga falló»
(`zlib.error` queda fuera), pero eso es conservador, no un agujero.

---

## No bloqueante (ronda 3)

1. **Quitar `EOFError`/`gzip.BadGzipFile` de la tupla no rompe ningún test**
   (mutación sobrevive, 92 passed). No es una laguna real: para la forma que sí
   está probada —truncado *después* de entregar líneas— el comportamiento es
   idéntico con la tupla vieja y con la nueva (propaga, una sola apertura), así
   que **no hay nada observable que clavar ahí**. La rama donde el cambio sí
   altera el comportamiento (`EOFError`/`BadGzipFile` con `produced == 0` →
   ahora se reintenta) es la que no tiene test. Un caso más en el helper
   `_CutOffStream` lo cerraría. Lo señalo por completitud, no como deuda seria.
2. **`raise_for_status()` y el reintento de `HTTPStatusError` siguen sin test**
   (ambas mutaciones sobreviven). Es el mismo no bloqueante de la ronda 2, sin
   cambios y sin agravarse.

**Sobre las fases 3-4 de `docs/operations.md` (la salvedad que registra el
implementer): lo doy por aceptable tal como está.** El documento **no** promete
más de lo que sostiene: la tabla marca el RSS de esas dos filas como «< fase 2»
en vez de dar un número inventado, los tiempos llevan tilde (`~14 min`, `~3 min`)
y justo debajo hay una frase que separa explícitamente lo medido con el código
de esta rama (fases 1 y 2, `resource.getrusage`, pasada completa) de lo que es
una pasada equivalente (fases 3 y 4). Los números que exigía B3 —tiempo, disco y
el pico de memoria— son los medidos. Único matiz cosmético: la frase de cabecera
(«Medido el 2026-09-04 contra los dumps reales») convendría que dijera «salvo
donde se indica», porque la salvedad va cuatro líneas más abajo. No es motivo de
nada.

**Sigue sin ser verificable desde el repo** (y lo repito para que no se pierda al
cerrar la feature): los 574 MB de pico, los 7.516 s de la fase 2, las 19.221
obras elegidas, los 3,1 MB de disco, las 392.466 obras con edición y la tabla de
ratios de `sys.intern`. Son un run de dos horas contra archive.org. Coherentes
entre sí y con el resto del documento, pero **declarados, no comprobados**.

---

## Checkpoints (ronda 3)

- **C1** `init.sh` sin errores: **[x]** — exit 0, verificado por mí.
- **C2** sin `print()` de debug: **[x]**
- **C3** sin TODOs sin contexto: **[x]**
- **C4** `ruff check` + `format --check`: **[x]**
- **C5** todos los tests pasan: **[x]** — 1414 passed.
- **C6-C8** modelos y migraciones: **n/a** — no se toca el esquema.
- **C9-C13** endpoints: **n/a** — ninguno nuevo; `bruno/` sin cambios.
- **C14** fechas convertidas explícitamente: **[x]**
- **C15** ids externos únicos por test: **[x]**
- **C16-C17** fallback on-demand: **n/a**
- **C18** sync idempotente: **[x]**
- **C19** un error no aborta el resto: **[x]**
- **C20-C22** separación de capas: **[x]**

**Ningún checkpoint en `[ ]`.**

---

## Los 11 criterios de aceptación

| # | Criterio | |
|---|---|---|
| 1 | Streaming sin disco ni carga en memoria | **[x]** verificado leyendo el camino completo: ni un `open(...,"wb")`; memoria acotada por la whitelist |
| 2 | Decisión razonada sobre `ddc`/`lcc` | **[x]** vía A, con la vía B descartada por hechos y documentada |
| 3 | `SEED_TOP_N_BOOKS` coherente y comentario corregido | **[x]** el comentario falso está corregido; el valor queda como decisión del leader, documentada en tres sitios |
| 4 | Features 72 y 73 preservadas, con test sobre datos reales | **[x]** reproducido por mí sobre el fixture: agregados y géneros idénticos a `search.json` |
| 5 | Autoría desde `ol_dump_authors` | **[x]** cero llamadas a `get_author` |
| 6 | Pipeline reanudable | **[x]** artefacto atómico + salto de fase + `--force`, los tres sujetos por mutación |
| 7 | Coste en tiempo y disco documentado | **[x]** con la salvedad de las fases 3-4, aceptable como está |
| 8 | `search.json` sigue sirviendo búsqueda y fallback | **[x]** `jobs.py` es un renombrado puro, verificado mecánicamente; el resto de `backlogg/books/` intacto |
| 9 | `docs/external-apis.md` y `docs/seeding-plan.md` actualizados | **[x]** y corregida la línea falsa de rate limits |
| 10 | Tests sobre fragmento fijado, sin red | **[x]** comprobado con proxies apuntando a un puerto muerto |
| 11 | `bash init.sh` en verde | **[x]** exit 0, 1414 passed |

---

## output de `bash init.sh` (ronda 3)

```
── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
308 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
1414 passed in 33.64s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
EXIT=0
```

---

## Cierre

La feature está **correcta y sujeta por sus tests**, que es el listón. Los tres
bloqueantes de la ronda 1 y el de la ronda 2 se cerraron con pruebas que muerden
—lo he comprobado mutando en las tres rondas, no leyendo informes— y el código
nuevo de esta última ronda es una mejora real: convierte un comportamiento que
era correcto por accidente del tipo de excepción en uno correcto por regla, con
la regla clavada por dos tests y un seguro anti-vacuidad dentro del propio test.

Quedan dos nits de cobertura sin consecuencia práctica y una lista de números
declarados que no son verificables desde el repo, todo anotado arriba para que
no se pierda.

**APPROVED.**
