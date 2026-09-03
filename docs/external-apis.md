# External APIs

## TMDB (Movies & Series)

- **Auth**: API key via header `Authorization: Bearer <TMDB_API_KEY>`
- **Base URL**: `https://api.themoviedb.org/3`
- **Rate limits**: ~50 req/s documentado. La siembra se queda en 30-40
  (`TMDB_SEED_CONCURRENCY=8` ≈ 32 req/s con el RTT medio de TMDB).
- **Key endpoints used**:
  - `GET /discover/movie` — **enumeración del catálogo de películas** (feature 86)
  - `GET /discover/tv` — **enumeración del catálogo de series** (feature 86)
  - `GET /movie/{tmdb_id}?append_to_response=credits,external_ids` — hidratación
    de una sola petición (detalle + reparto + ids externos)
  - `GET /tv/{tmdb_id}?append_to_response=credits,external_ids` — ídem para series
  - `GET /search/movie?query=` — on-demand fallback search
  - `GET /search/tv?query=` — on-demand fallback
  - `GET /movie/{tmdb_id}/credits` — cast & crew; sigue en uso **solo** en la
    ruta on-demand y en el backfill dirigido (feature 85), donde la fila ya
    existe y solo faltan los credits
  - `GET /tv/{tmdb_id}/credits` — ídem
  - `GET /person/{person_id}` — person detail
  - `GET /movie/popular`, `GET /tv/popular` — **ya no se usan para sembrar**.
    Los métodos `get_top_movies`/`get_top_series` siguen existiendo como
    clientes documentados de esos endpoints, pero ningún job los llama.

### Enumeración por `/discover` (feature 86)

El catálogo de movies y series se define por **umbral de `vote_count`**, no
por número de ítems. La enumeración trocea por año de estreno:

```
GET /discover/movie?page=N
    &include_adult=false&include_video=false
    &sort_by=primary_release_date.asc
    &vote_count.gte=25
    &primary_release_date.gte=YYYY-01-01&primary_release_date.lte=YYYY-12-31

GET /discover/tv?page=N
    &sort_by=first_air_date.asc
    &vote_count.gte=25
    &first_air_date.gte=YYYY-01-01&first_air_date.lte=YYYY-12-31
```

Detalles que importan:

- `include_adult=false` e `include_video=false` **solo existen en
  `/discover/movie`**. `/discover/tv` no tiene `include_video` y no expone
  contenido adulto por esta vía, así que no hay parámetro equivalente.
- `sort_by` es por **fecha**, no por popularidad. Un orden por popularidad se
  reordena mientras se pagina, que es exactamente el defecto que hundía el
  recorrido por offset de `/popular`.
- **Tope de 500 páginas**, igual que `/popular`. La guardia es explícita:
  `backlogg/scheduler/discovery.py` lee `total_pages` de la primera página de
  cada ventana y, si supera el tope, **trocea el año en sus doce meses**. Si un
  mes siguiera pasándose, el run no aborta: enumera las 500 páginas que TMDB
  sirve y **reporta la ventana truncada** (`EnumerationStats.truncated_windows`,
  y el script sale con código 2). Medido con `vote_count ≥ 25` el peor año usa
  el 22% del cupo, así que hoy no se dispara nunca.
- **Limitación conocida**: un ítem sin fecha de estreno no cae en ninguna
  ventana y por tanto no se enumera. Con `vote_count ≥ 25` es un caso residual;
  esos ítems siguen entrando por el fallback on-demand y por el fan-out de
  búsqueda.

### `append_to_response` (feature 86)

`GET /movie/{id}?append_to_response=credits,external_ids` devuelve el detalle,
el cuerpo de `/movie/{id}/credits` bajo la clave `credits` y el de
`/movie/{id}/external_ids` bajo `external_ids`, **al precio de una sola
petición**. La hidratación pasó de 2 peticiones por ítem a 1: sobre 57.135
movies son 57.135 peticiones ahorradas.

Consecuencia operativa: en el job nocturno de movies/series ya no existe un
fallo *independiente* de credits. Si la petición falla, falla el ítem entero y
cuenta en `errors`. `people_errors` sigue vivo pero ahora solo recoge fallos de
**escritura** de people/credits (filas rechazadas por el lote, o el fallback
por ítem), no de red.

- **⚠️ Slug strategy**: la afirmación histórica de este documento («TMDB
  provides its own `slug` field, use it directly») **es incorrecta**. El
  adaptador genera los slugs localmente con `_slugify(título)-año`
  (`backlogg/movies/adapters/tmdb.py`). Mantenerlo así: es lo que permitiría
  que las URLs sobrevivieran a un cambio de fuente sin perder posicionamiento.
- **⚠️ Uso comercial**: la licencia gratuita es solo para uso **no comercial**.
  Sus términos cuentan como comerciales, entre otros, cobrar a usuarios, poner
  publicidad, «operar sitios web que generan ingresos recomendando contenido» y
  **«entrenar sistemas de machine learning / IA con datos de TMDB»**. Tarifa
  comercial reportada: 149 $/mes por debajo de 1 M$ de facturación y 2 M de
  usuarios. Contacto: `sales@themoviedb.org`.
  - Consecuencia práctica para la **feature 75** (embeddings): generar
    embeddings sobre las sinopsis de TMDB podría caer bajo esa cláusula y
    activar la licencia comercial **antes** de monetizar.
  - **Decisión del usuario (2026-09-02): riesgo aceptado.** La feature 75 se
    implementa embebiendo título, géneros y sinopsis de TMDB, sin consulta
    previa a `sales@themoviedb.org`. Se descartó la opción conservadora
    (embeber solo título y géneros para movies/series, sinopsis completa solo
    en books/games, que son CC0 e IGDB). Exposición asumida: 149 $/mes
    reclamados antes de monetizar. Plan de repliegue si TMDB reclama:
    regenerar los vectores de movies/series sin la sinopsis, o limitar la capa
    semántica a books y games — `item_embeddings` es polimórfica por
    `item_type`, así que replegarse es reprocesar dos tipos, no rediseñar.
- **⚠️ Caché**: prohibido cachear datos de TMDB más de **6 meses**. Desde la
  feature 86 esto lo cubre la **rotación de refresco**: cuando no quedan
  targets pendientes trabajables, la rebanada nocturna se llena con los ítems de
  `last_synced_at` más antiguo (`get_stale_catalog_external_ids`). Que esa
  condición sea alcanzable depende de la retirada de targets inalcanzables
  (`docs/seeding-plan.md` §3): sin ella la rotación no se dispararía nunca y la
  obligación de los 6 meses se perdería. Para cubrir
  57.135 movies en 180 días hacen falta ~318/noche, así que
  `SYNC_SLICE_SIZE_MOVIES` debe estar en ~350; series necesita ~61. Ver
  `docs/seeding-plan.md` §2.3.
- **external_ids source value**: `TMDB`

## Open Library (Books)

- **Auth**: none required
- **Base URL**: `https://openlibrary.org`
- **Rate limits**: none enforced — suitable for batch sync
- **Key endpoints used**:
  - `GET /search.json?q=<filtered>&sort=readinglog&offset=&limit=` — seed/nightly sync popular books (dos streams filtrados, EN y ES; ver *Popular-books strategy*)
  - `GET /search.json?title=&limit=` — on-demand fallback search
  - `GET /works/{olid}.json` — work detail (modeled at work level, not edition)

- **Popular-books strategy**: the sync uses `search.json` sorted by `readinglog` —
  the count of users who shelved the work as want-to-read/reading/read — with native
  `offset`/`limit` pagination (verified up to offset 9900; offsets de 50.000 y 100.000
  también responden 200). La query **ya no es `q=*:*`**: desde la feature 73 son dos
  streams filtrados y disjuntos, inglés y castellano, intercalados por cuota
  (ver *Calidad del catálogo* más abajo para las queries exactas y los umbrales).
  Do **not** use:
  - `/trending/weekly.json` — capped at a few hundred entries, catalog cannot grow
  - `sort=rating` — surfaces obscure books with very few ratings
  - `sort=edition_count` — does not exist (returns HTTP 500)

  **Page size**: el adaptador pagina de 100 en 100 (`_OL_MAX_PAGE_SIZE`).
  `limit=1000` está **verificado en vivo** (devuelve 1000 docs y reduciría las
  peticiones ×10), pero se mantiene en 100 **a propósito**: subirlo cambia el
  contrato de paginación sobre el que assertan los tests de los llamadores y es
  una optimización ajena a la feature 73. Queda como trabajo futuro.

  Request the field set
  `key,title,author_name,first_publish_year,cover_i,isbn,ddc,lcc,subject_facet,edition_count`
  (the shape `book_to_dict` consumes — constant `_OL_SEARCH_FIELDS` in
  `backlogg/books/adapters/open_library.py`). `subject` se eliminó en la
  feature 72: solo se consumía para derivar géneros, y eso ahora sale de
  `lcc`/`ddc`. `edition_count` se añadió en la feature 73: Solr filtra por él
  sin devolverlo, pero se pide para poder auditar una página contra el umbral
  que la seleccionó.

  ⚠️ `sync_books` (`backlogg/scheduler/jobs.py`) **no** pasa el doc crudo al
  adaptador: reconstruye a mano un `search_doc` reducido campo a campo. Todo
  campo nuevo del field set hay que copiarlo también ahí o el job nocturno lo
  pierde en silencio mientras la búsqueda on-demand sigue funcionando (fue
  exactamente el bug del issue #17 con `isbn`). Excepción documentada en el
  propio código: `edition_count` **no** se copia porque `book_to_dict` no lo
  lee — es un campo de filtro/auditoría, no de persistencia.
- **Clasificación y calidad de catálogo (investigación 2026-08-29, clasificación implementada en la feature 72)**: los dos
  problemas observados en producción —géneros basura y catálogo basura— **no
  requieren cambiar de proveedor**. Ambos se resuelven dentro de Open Library.

  **Géneros.** El adaptador pedía solo `subject`, el peor campo disponible:
  una folksonomía sin control, con **media de 40 subjects por obra** (de ahí
  las 510 etiquetas distintas con solo 370 libros ingeridos, 397 de ellas
  usadas una sola vez). `search.json` expone además tres campos que no se
  pedían. Cobertura medida sobre las 200 obras más estanteadas:

  | Campo | Cobertura | Naturaleza |
  |---|---|---|
  | `lcc` (Library of Congress) | 89 % | Taxonomía controlada y jerárquica |
  | `ddc` (Dewey Decimal) | 78 % | Taxonomía controlada y jerárquica |
  | `subject_facet` | 99 % | Más limpio que `subject`, aún folksonómico |
  | `subject` (el que se usaba antes de la feature 72) | 99 % | Sin control, ~40 por obra |

  Subjects en formato BISAC (`BUSINESS & ECONOMICS / ...`): solo **17 %** — no
  sirven como taxonomía de respaldo.

  **Uso recomendado, y su límite.** DDC y LCC clasifican por **disciplina y
  procedencia, no por género tal y como lo entiende un lector**: `813.6` es
  "ficción estadounidense contemporánea", así que *It Ends With Us* y *It* de
  Stephen King comparten clasificación. Por tanto:
  - `ddc`/`lcc` → eje **grueso y limpio** (ficción vs ensayo, literatura vs
    psicología vs historia). Excelente para descartar ruido y para filtrar.
  - Género de cara al lector (fantasía, terror, romance) → `subject_facet`
    normalizado + mapeo manual de la cabeza + embeddings para la cola
    (ver `docs/recommendations-plan.md`, features 76-78).

  **Decisión implementada (feature 72).** `book_to_dict` deriva los géneros con
  `_derive_genres`, que emite **solo** etiquetas de un vocabulario controlado y
  cerrado (`_CONTROLLED_GENRES`, ~32 entradas: Fiction, Poetry, Drama, Essays,
  Literature, Children's & YA, Philosophy, Psychology, Self-Help, Religion,
  History, Biography, Geography & Travel, Social Sciences, Economics &
  Business, Political Science, Law, Education, Music, Art, Language, Science,
  Mathematics, Computing, Medicine & Health, Technology, Agriculture, Cooking,
  Military & Naval, Sports & Recreation, Reference, Library & Information
  Science). Precedencia — **`lcc` decide la disciplina y `ddc` es su
  respaldo**, con un único refinamiento acotado dentro de literatura:

  1. **`lcc`** (primaria, 89 %). Open Library la devuelve normalizada y
     ordenable (`"PS-3568.00000000.O243 D3 1998"`). Se extrae la clase de
     letras inicial y se busca de más específico a menos (3 → 2 → 1 letra), así
     que `BF` → Psychology gana a `B` → Philosophy, `HD` → Economics & Business
     a `H` → Social Sciences, y `PZ` a `P` → Language.

     ⚠️ **`lcc` es multivalor y hay que quedarse con la clase dominante, no
     agregarlas todas.** Medido sobre las 100 obras más estanteadas: 87 traen
     `lcc` y **45 de esas 87 (51 %) traen más de una clase distinta** — una obra
     popular acumula la signatura de cada edición catalogada. Agregar produce
     etiquetas falsas a partir de ediciones marginales: *L'étranger* trae 40
     entradas `PQ` (literatura francesa) y 2 `PZ` de una edición escolar, y esas
     dos bastaban para etiquetar a Camus como infantil. Se cuenta la frecuencia
     de cada clase y gana la más frecuente; **el desempate es la primera
     aparición en la lista original**, nunca el orden de un `set` ni un
     `most_common` sin desempate, que no son estables entre ejecuciones. Las
     entradas no parseables o de clase no mapeada **no votan**, así que una
     clase desconocida no puede ganar y dejar el libro sin géneros: basta con
     que **una** entrada mapee para que gane, aunque sea minoritaria
     (`['YY','YY','YY','PS']` → `PS`), y solo se cae a `ddc` cuando **ninguna**
     mapea. En la práctica es inalcanzable sin datos corruptos: todas las letras
     de clase LCC reales están mapeadas (las que faltan —I, O, W, X, Y— no
     existen en LCC).

     ⚠️ **`PZ` no es "infantil": depende del número.** `PZ1`-`PZ4` es *ficción
     en inglés para adultos* (una práctica antigua de LCC); lo juvenil empieza
     en `PZ5` (*juvenile belles lettres*), y `PZ7` es ficción juvenil. Open
     Library pone el número en la segunda posición: `"PZ-0004…"` → `PZ4` →
     solo Fiction (*The Shining*, *L'étranger*); `"PZ-0007…"` → `PZ7` → Fiction
     + Children's & YA (*Harry Potter*, *The Fault in Our Stars*);
     `"PZ-0010.731…"` → `PZ10.3`, también juvenil. Sin número parseable se emite
     solo Fiction, que es lo único que comparte toda la clase.
  2. **`ddc`** (respaldo, 78 %). Se dispara cuando no hay `lcc`, y también
     cuando la hay pero su clase no está mapeada o no es parseable (`YY-0001`
     cae aquí). Se normaliza descartando todo carácter no numérico —así
     `813/.54`, `j813.54` y `813.54 B` dan lo mismo— y se mapea por centenas, con refinamientos que si no se perderían
     dentro de su clase (`004`-`006` Computing, `15x` Psychology, `158`
     Self-Help, `641` Cooking, `78x` Music, `796` Sports, `91x` Geography &
     Travel, `92`/`920` Biography — `929` queda excluido, es
     genealogía y heráldica, no biografía). Dentro de `8xx` el **tercer dígito es la
     forma literaria** y sí da señal de lector: `8_1` Poetry, `8_2` Drama,
     `8_3` Fiction, `8_4` Essays (más Literature). También se aceptan las
     notaciones entre corchetes `[Fic]` y `[E]`.
  3. **`subject_facet`** (99 %, solo si no hay ninguna de las dos, ~10 % de los
     casos). **No se acepta en crudo**: se compara por igualdad exacta
     (case-insensitive, espacios colapsados) contra una tabla de sinónimos que
     resuelve al mismo vocabulario. Lo que no casa se descarta.

  **El refinamiento de forma literaria.** Cuando —y solo cuando— la clase LCC
  resuelve a `literature`, se lee **además** el dígito de forma del `ddc` y se
  antepone: `PS` + `813.54` → Fiction + Literature, `PS` + `814.54` → Essays +
  Literature. No es una mezcla arbitraria de las dos taxonomías, sino el único
  punto donde son complementarias en vez de redundantes: LCC clasifica la
  literatura por **procedencia y lengua** (`PR` inglesa, `PS` estadounidense) y
  **nunca codifica la forma**, mientras que DDC la codifica exactamente en el
  tercer dígito de `8xx`. La disciplina la sigue decidiendo `lcc`.

  Sin este refinamiento, una novela, un poemario y un libro de ensayos bajo
  `PS` saldrían los tres como "Literature" a secas, y el eje ficción-vs-ensayo
  —que es lo que esta clasificación existe para dar— solo se entregaría para el
  ~11 % de libros sin `lcc`. Si el registro no trae `ddc`, o su dígito de forma
  no es uno de los cuatro, el libro se queda en "Literature": es la respuesta
  honesta cuando no hay señal de forma.

  Fuera de las clases de literatura **no se refina nunca**: ahí ambas
  taxonomías clasifican por disciplina y solo producirían etiquetas casi
  duplicadas. `QA` + `813.54` sale como Mathematics, no como ficción.

  Cada fuente se filtra contra el vocabulario **antes** de comprobar si está
  vacía, para que una entrada errónea en una tabla de mapeo degrade a la fuente
  siguiente en vez de dejar el libro sin géneros en silencio. Se mantiene el
  tope de 5 géneros por libro y la deduplicación por slug; en la práctica salen
  1-3.

  **Qué pasa con el resto.** Un libro sin `lcc`, sin `ddc` y con
  `subject_facet` que no casa con nada **se queda sin géneros**. Es un
  resultado aceptado y explícito: mucho mejor que persistir "Triathlon".

  Adoptar `ddc`/`lcc` permitió además **eliminar `_is_clean_genre`**, su regex
  `_CLEAN_SUBJECT_RE` y `_GENRE_ALLOWLIST`
  (`backlogg/books/adapters/open_library.py`): la heurística de longitud,
  paréntesis y comas que intentaba arreglar aguas abajo un problema que se
  resuelve en el origen eligiendo otro campo.

  Las etiquetas basura ya persistidas se purgaron con la migración
  `0033_books_controlled_genres_purge`, que preserva los libros con `genres`
  en `locked_fields` (ediciones manuales de admin, feature 49). Los géneros son
  datos derivados: se repueblan con `uv run python scripts/backfill_sync.py book`.

  **Calidad del catálogo — filtro implementado en la feature 73.**
  `q=*:*&sort=readinglog` devuelve lo que más gente estantea en Open Library,
  y ahí entra mucha entrega suelta de serialización, tie-in de videojuego y
  ficha a medias: *Batman and Robin Vol. 1*, *Ultimate Spider-Man Vol. 6*,
  *Metal Gear Solid vol. 1*, *Encyclopaedia Eorzea Volume III*, *Ultimate
  FFXIV Cookbook Vol. 2*, *Ferno the Fire Dragon (Beast Quest #1)*. No es un
  fallo de la API: es lo que esa señal mide.

  **El criterio es la notoriedad de la obra, no su clasificación.** Es el
  punto que costó dos rondas acertar. No se trata de dejar fuera un género:
  el ensayo y la autoayuda (*Atomic Habits*, *Sapiens*, *Thinking, Fast and
  Slow*) son catálogo legítimo de una app de backlog de lectura, y la novela
  gráfica con identidad propia (*Watchmen*, *Maus*, *Persepolis*, *V for
  Vendetta*, *Sandman*, *Fun Home*, *Blankets*, *Bone*, *Akira*, *Death
  Note*, *Heartstopper*) también. Lo que sobra es el volumen suelto de una
  serialización, y eso lo separa **`edition_count`**: cuántas ediciones ha
  tenido la obra.

  Umbrales calibrados en vivo contra `search.json` (2026-08-30). Queries
  finales, ambas verificadas:

  ```
  EN (numFound = 16.959):
    q=language:eng AND number_of_pages_median:[100 TO *]
      AND readinglog_count:[20 TO *] AND edition_count:[10 TO *]
    &sort=readinglog

  ES (numFound = 1.858):
    q=language:spa AND NOT language:eng AND number_of_pages_median:[100 TO *]
      AND readinglog_count:[5 TO *] AND edition_count:[2 TO *]
    &sort=readinglog
  ```

  Pool total 18.817 obras, ~190× el `SEED_TOP_N_BOOKS` por defecto. La primera
  página EN es *Atomic Habits*, *The 48 Laws of Power*, *It Ends With Us*,
  *Harry Potter 1*, *A Game of Thrones*, *It*.

  **Justificación de cada pieza:**

  | Fragmento | Por qué | Medido |
  |---|---|---|
  | `edition_count:[10 TO *]` (EN) | El discriminante. Hueco limpio entre la entrega suelta y la novela gráfica canónica: *Ultimate Spider-Man Vol. 6* tiene 3 ediciones, *Batman and Robin Vol. 1* 1, *Metal Gear Solid* 3; la canónica con menos es *Bone*/*Blankets* con 11 y *Death Note* con 12, y de ahí para arriba (*Akira* 15, *Persepolis* 21, *Heartstopper* 23, *V for Vendetta* 36, *Watchmen* 43, *Maus* 66). **Subsume además la completitud de ficha**: 0 docs sin portada, año ni autor en 4 de 5 muestras de 1.000 | 52.067 → 16.959 a rl≥20 |
  | `readinglog_count:[20 TO *]` (EN) | La cola aguanta limpia hasta el final verificado (offset 15.900: le Carré, Banville, Javier Marías, Rosario Castellanos, Chaucer). La variante conservadora rl≥50 da 8.497 y pasa la misma regresión; se elige 20 por margen para el backfill | 16.959 |
  | `number_of_pages_median:[100 TO *]` | Descarta folletos y panfletos; recorta 9-12 %. ≥150 empieza a comerse novelas cortas legítimas sin ganancia | — |
  | `language:spa AND NOT language:eng` + `readinglog_count:[5 TO *]` (ES) | `language` es **multivaluado a nivel de work** (agrega los idiomas de todas las ediciones), así que `language:(eng OR spa)` es indistinguible de `language:eng` (29.476 vs 29.326) y devuelve la misma lista inglesa: una query bilingüe única sembraría **cero** libros en castellano. La señal de estantería es ~10× menor en castellano, de ahí el umbral propio | 4.508 |
  | `edition_count:[2 TO *]` (ES) | Con ed≥2 la cola es Arguedas, Benedetti, Barthes, Saramago, Martín Gaite, Elvira Lindo, Fernanda Melchor. **No puede subir a 3**: *Reina roja* tiene exactamente 2 ediciones (ed≥3 deja 976 obras y la expulsa). `cover_i:[* TO *]` se evaluó como alternativa y es peor palanca: da 3.466 obras pero la cola profunda es *101 Posturas Sexuales* y manuales técnicos autoeditados | 4.508 → 1.858 |

  **Por qué NO hay cláusula de clasificación.** La primera versión de esta
  feature filtraba por `(ddc:8* OR lcc:P*) AND NOT lcc:PE* AND NOT ddc:80*`
  y estaba **invertida en las dos direcciones**: dejaba el catálogo en
  solo-literatura (fuera *Atomic Habits* con `ddc 155.24`, *Thinking, Fast
  and Slow* `153.42`, *The Psychology of Money* `332.02`, *Educated*, *Becoming*)
  y **no** quitaba los cómics, que entraban justo por `lcc:P*` — LCC
  PN6700-6790 *es* "Comic books, graphic novels". Se retiró entera.

  **Y por qué tampoco se puede sustituir por una exclusión de cómics.** No hay
  señal fiable en Solr, medido sobre un pool de 17.553 obras:

  | Señal | numFound | Veredicto |
  |---|---|---|
  | `ddc:741.5*` | 218 (1,2 %) | Cobertura parcial: se le escapan Ultimate Spider-Man, Naruto, Berserk, Maus, Metal Gear Solid, y marca *Frankenstein* (lleva `741.5973` por sus adaptaciones) |
  | `lcc:PN-67*` / `lcc:PN67*` / `lcc:PN-6*` | **0** | El campo `lcc` **no admite comodines de prefijo**: los valores están normalizados a `XX-NNNN.NNNNNNNN` y el guion rompe el parseo |
  | `lcc:PN\-67*` (escapado) | 9 | Incoherente |
  | `lcc:PN\-6728*` (escapado) | 13 | **Un prefijo más largo devuelve MÁS documentos** → el wildcard no es fiable |
  | `lcc:[PN-6700 TO PN-6799]` | 276 | El rango sí funciona, pero contamina: el `lcc` de un *work* agrega el de todas sus ediciones, así que una adaptación en cómic mete a *Pride and Prejudice*, *Frankenstein* y *Dracula* en el rango |
  | `subject_facet:"Graphic novels"` (y `"Manga"`, `"Comic books, strips"`) | 0-1 | **`subject_facet` no es consultable**, solo devolvible: cualquier cláusula sobre él es silenciosamente inútil |
  | `subject:comics` | 494 | Consultable pero ruidoso: *1984* lleva ese subject |

  **Filtro por patrón de título: evaluado y descartado.** Casar `Vol. N` /
  `Volume N` / `#N` / `(Serie, #N)` sobre los docs recibidos afecta al
  0,6-1,9 % del pool, pero lo que hay ahí dentro son novelas de serie
  legítimas (*C is for Corpse (Kinsey Millhone, #3)*, *The Grey King (The Dark
  is Rising #4)*, *Outcast of Redwall (Redwall #8)*). Sobre las listas de
  control elimina **4 de 12** de los que deben entrar —*Heartstopper Volume
  1*, *Akira Vol. 1*, *Death Note Vol. 1*, *Monstress Vol. 1*, un **33 %** de
  las novelas gráficas canónicas— y de los que debe quitar, 6 de 7 ya caen por
  los umbrales numéricos. **Ganancia neta real: 1 documento**, a cambio de
  ~170-340 obras. No se aplica.

  **Deduplicación: evaluada y descartada.** Las colisiones de (título
  normalizado, primer autor) son 0,0-1,1 % en muestras de 1.000 y casi
  ninguna es un duplicado real: son obras distintas que el normalizador
  colapsa al quitarles el número de volumen (*Heartstopper* 1/2/3, *Amulet*
  1/2). El caso que motivó la idea (*Metal Gear Solid vol. 1* / *Metal Gear
  Solid Volume 1*) no sobrevive a los umbrales numéricos.

  **Único filtro en código: `doc["key"].endswith("W")`.** `search.json`
  devuelve de vez en cuando una key de *edición* (`/works/OL9394106M`, sufijo
  `M`) como si fuera una obra: son ediciones sin work padre. ~1 de cada 1.000
  docs sin `edition_count`, **0** con `ed≥10`. Se descarta **dentro del bucle
  de paginación de `_fetch_seed_stream`**, no en `get_popular_books`: ahí el
  hueco se rellena con el siguiente doc del stream, mientras que descartar
  después de repartir los slots devolvería una página corta sin que ningún
  stream esté agotado — y una página corta es justo lo que `_next_offset`
  interpreta como fin de listado para envolver el cursor a 0. El fin de
  resultados se sigue decidiendo sobre la página **cruda**
  (`len(docs) < per_page`), que es la única señal que da OL.

  **Costes aceptados.**
  - Se pierde *Monstress, Vol. 1* (ed=4): obra reciente y de nicho. Es el
    precio directo de usar la notoriedad como criterio.
  - Entra ruido residual **de otra clase**: libros de texto académicos
    (*Precalculus With Limits*, *iGenetics*, *Advanced Accounting*,
    *Management Information Systems*). Son legítimamente populares y muy
    reeditados, y **ninguna señal medida los distingue**. Candidatos a una
    feature aparte, no a endurecer estos umbrales.
  - Sobrevive *E Natale, Stilton! (#12)* (ed=17, rl=383). Mirado de cerca es
    un libro infantil real y popular, no una ficha basura.
  - Los títulos en alfabeto no latino (*Доктор Живаго*, *人間失格*) aparecen en
    ambos streams porque `language` agrega todas las ediciones.
  - *Cien años de soledad* y *La sombra del viento* **no** están en el stream
    ES: tienen ediciones en inglés y las excluye `NOT language:eng`. Es una
    propiedad preexistente del diseño de dos streams disjuntos.

  **Fugas puntuales**: para un título concreto que se cuele, la herramienta
  correcta es una **denylist explícita de `work key`**, no endurecer los
  umbrales.

  **Intercalado EN/ES.** Las dos queries son disjuntas por construcción, así
  que se paginan por separado y se unen sin deduplicar. Como una sola query
  ordenada por `readinglog` global daría cero castellano en el top 100, el
  adaptador intercala **una obra en castellano cada `BOOKS_SEED_ES_EVERY_N`
  huecos** del índice global `i`:

  ```
  is_es(i)     = (i % N) == N - 1
  es_offset(i) = i // N
  en_offset(i) = i - (i // N)
  ```

  Es función pura del índice global, así que el cursor de
  `backlogg/scheduler/jobs.py` sigue siendo **un solo entero**. Si un stream
  se agota, sus huecos se rellenan con el otro (continuando su propio offset)
  para no devolver una página corta: `_next_offset` interpretaría esa página
  corta como fin de listado y envolvería el cursor a 0.

  `BOOKS_SEED_ES_EVERY_N=0` desactiva el stream español **de verdad**: no se
  emite su query ni siquiera como relleno. Es la palanca para el caso "Open
  Library rompe la query ES", donde emitirla igualmente agotaría el
  presupuesto de reintentos y tumbaría el slice entero. La asimetría es
  deliberada: `every_n=1` es un ajuste de cuota, no un kill switch del inglés,
  y guardar esa rama devolvería páginas cortas.

  ⚠️ **El relleno solapa slices consecutivos** (aceptado, por diseño). El
  backfill consume docs del otro stream *por delante* de su propio cursor,
  pero el slice siguiente recalcula su offset con la fórmula pura
  (`en_offset(offset + limit)`), que es menor. Con el stream ES agotado
  —a partir de un offset global de ~18.580 con los defaults— cada slice
  repetiría `es_count` docs ingleses del slice anterior. **No estanca el
  catálogo** (el offset propio de cada stream avanza `en_count` por slice) y
  los upserts son idempotentes, así que el efecto se limita a reingestar unos
  pocos libros ya conocidos. Es el precio deliberado de no devolver nunca una
  página corta, que sí envolvería el cursor a 0.

  **No confundirlo con un duplicado dentro de una misma página**, que sí era
  un bug y está corregido. El backfill arranca desde el **offset crudo** donde
  el stream dejó de leer, que `_fetch_seed_stream` devuelve como tercer
  elemento de su tupla. Reconstruirlo como `en_offset + len(en_docs)` es
  incorrecto desde que existe el descarte de keys huérfanas: `len(en_docs)`
  está en espacio **filtrado**, así que por cada key descartada el backfill
  repedía el último documento que acababa de devolver y la página salía con
  un duplicado (10 ítems, 9 distintos). Como `sync_books` hace upsert por
  ítem, el fallo era silencioso: inflaba `synced` y sembraba un libro distinto
  menos. Regla: **toda aritmética de offset va en espacio crudo de la API**;
  el único contador en espacio filtrado es cuántos docs útiles llevamos.

  **Guarda de `numFound`.** El adaptador lee el `numFound` de ambos streams y
  emite un `warning` si `numFound_en + numFound_es < SEED_TOP_N_BOOKS`. Sin
  ella, unos umbrales demasiado duros dejarían el catálogo estancado **en
  silencio** (mismo modo de fallo que `/trending/weekly.json` en la feature 25).
  La comparación es contra el pool **total**, así que un stream ES minúsculo
  junto a un EN enorme **no** dispara aviso aunque el ES se agote en cada
  slice (y active el solapamiento de arriba). Vigilar por stream sería la
  mejora natural si algún día el pool ES se estrecha.

  **Sintaxis Solr — reglas obligatorias** (cada una medida; incumplirlas da 0
  resultados o ignora el filtro sin avisar):

  | Regla | Qué pasa si se incumple |
  |---|---|
  | `AND`/`OR`/`NOT` en MAYÚSCULAS | `and`/`or` en minúsculas → `numFound=0` |
  | Rangos **sin** comillas | `readinglog_count:"[20 TO *]"` → 947.088, se parsea como texto y el filtro se ignora |
  | Paréntesis alrededor de todo `OR` | `language:eng OR language:spa` suelto → 4.958, precedencia rota |
  | `lcc` no admite comodines de prefijo | `lcc:PN-67*` → 0; escapado, incoherente. Solo el rango `[PN-6700 TO PN-6799]` funciona, y contamina |
  | `subject_facet` no es consultable | Cualquier cláusula sobre él se ignora en silencio (0-1 resultados) |

  Sí funcionan, verificado: `language:*`, `number_of_pages_median:[N TO *]`,
  `readinglog_count:[N TO *]`, `edition_count:[N TO *]`, `cover_i:[* TO *]`,
  `key:/works/OLxxxW` (sin escapar las barras).

  El urlencode lo hace `httpx`; su codificación de espacios como `+` se
  verificó que devuelve el mismo `numFound` que el percent-encoding.

  **Dónde vive cada cosa:** los códigos de idioma son constantes
  (`backlogg/books/constants.py`) porque no son umbrales y una query cruda en
  una env var es frágil; los umbrales numéricos son env vars (`BOOKS_SEED_*`,
  tabla de más abajo). El filtro se aplica **solo** al camino de siembra
  (`get_popular_books`): `search_book` —fallback on-demand y fan-out de
  búsqueda— no se filtra, o buscar por título un ensayo reciente o una novela
  gráfica de nicho dejaría de encontrar nada.

- **Alternativas evaluadas y descartadas (2026-08-29)**: Open Library sigue
  siendo la fuente correcta, y es además la única de las cuatro verticales sin
  problema de licencia comercial (CC0).

  | Fuente | Por qué se descarta |
  |---|---|
  | Google Books | 1.000 peticiones/día: un backfill de 10.000 libros son 10 días de cuota. Sus términos advierten de que no es un sustituto de servicios comerciales |
  | ISBNdb | 15–300 $/mes, y es **centrado en ISBN/ediciones**, no en obras: choca con el modelo work-level del catálogo. Reintroduce una dependencia de pago recurrente sin resolver ningún problema que Open Library no resuelva ya |
  | Hardcover | GraphQL gratis, pero es **un competidor directo** (tracker de libros) y parte de sus datos vienen de Open Library y Google Books. Frágil como backbone |
  | BookBrainz | CC0 y bien modelado, pero cobertura demasiado pequeña |
  | Goodreads | API retirada en 2020 |
- **Slug strategy**: Open Library uses `/works/OL123W` format. Strip prefix, use `OL123W`
  as slug or derive from title.
- **Coverage note**: strong on classics and public domain; modern titles may have
  incomplete metadata (missing cover, publication date).
- **external_ids source value**: `OPEN_LIBRARY`
- **"Similar books" investigation (2026-08-16)**: no free/no-auth external API
  covers a "similar books" use case at the volume this project needs. Open
  Library exposes no related-works/recommendations endpoint. Google Books
  caps free usage at 100 requests/day (unworkable for on-demand fallback at
  catalog scale). Dedicated "find similar books" services require a paid API
  key. Conclusion: `GET /books/{slug}/similar` (feature 46) is computed
  entirely from local data (same author via `credits`, then genre overlap,
  then `rating_external`) instead of a new external dependency.
- **"Trending" investigation (2026-08-26, feature 68)**: Open Library has no
  "trending this week/day" endpoint (`/trending/weekly.json` exists but is
  capped at a few hundred entries and unrelated to what the catalog needs —
  see the popular-books note above, same reasoning applies). `GET
  /trending?type=book` is therefore computed entirely from local data: the
  same `rating_internal DESC NULLS LAST, rating_external DESC NULLS LAST`
  order already used by `GET /books` (feature 66), over items already
  persisted — no Open Library call happens for this endpoint. `period` is
  accepted but has no effect (no time-windowed signal exists to apply it to).

## IGDB (Games)

- **Auth**: Twitch client credentials OAuth2. Request token from
  `https://id.twitch.tv/oauth2/token`. Token expires — client must renew automatically.
- **Base URL**: `https://api.igdb.com/v4`
- **Required headers**: `Client-ID: <TWITCH_CLIENT_ID>`, `Authorization: Bearer <access_token>`
- **Query language**: IGDB uses a custom query language (not REST params):
  ```
  POST /games
  Body: fields name,slug,summary,cover.*,first_release_date,rating,rating_count,game_type,platforms.*;
        sort rating desc;
        limit 500;
  ```
- **Rate limits**: 4 requests/second on free tier. Use batching.
- **Key endpoints used**:
  - `POST /games` — seed and on-demand fallback. The single-game detail query
    (`get_game_by_slug`) also requests `similar_games.*` — IGDB's own curated
    "similar games" relation (id, name, slug, ...), used by
    `GET /games/{slug}/similar` (feature 45) instead of a local genre-overlap
    heuristic.
  - **Category allowlist** (feature 65): `get_top_games`'s query filters
    `game_type = (0,1,2,4,6,7,8,9)` — the 8 allowed IGDB categories, defined
    once in `backlogg/games/constants.py`. The other three ingestion paths
    (`get_game_by_slug`/`get_similar_games` in `backlogg/games/service.py`
    and `_ingest_games` in `backlogg/search/service.py`) cannot filter at the
    IGDB query level (single-slug lookups, or IGDB's free-text `search`
    endpoint has no `where` clause) so they check the mapped `game_type`
    against the same allowlist after `game_to_dict` and skip persisting
    (`upsert_game`) anything outside it. See `docs/schema.md`'s "Category
    allowlist" note for the full list and the excluded categories.
  - `POST /covers` — cover art
  - `POST /companies` — developer/publisher for company_credits
  - `POST /involved_companies` — join between games and companies

- **Slug strategy**: IGDB provides `slug` field directly.
- **Coverage note**: director data is sparse — only sync when available.
- **external_ids source value**: `IGDB`
- **"Trending" investigation (2026-08-26, feature 68)**: IGDB has no
  "trending this week/day" endpoint. `GET /trending?type=game` is therefore
  computed entirely from local data — same heuristic as `type=book` (see
  Open Library's "Trending" note above): `rating_internal DESC NULLS LAST,
  rating_external DESC NULLS LAST` order already used by `GET /games`
  (feature 66), over items already persisted. No IGDB call happens for this
  endpoint, and `period` is accepted but has no effect.

## TheTVDB v4 — EVALUADA Y APARCADA (2026-08-29)

> **No se usa.** Se evaluó como sustituto de TMDB y se descartó. Esta sección
> se conserva porque la investigación sigue siendo válida si el coste de TMDB
> llega a pesar: es toda la referencia necesaria para retomar el plan sin
> volver a investigarlo. Recogida del swagger oficial (`thetvdb/v4-api`,
> `docs/swagger.yml`) y de `thetvdb.com/api-information`.
>
> **Por qué se descartó**: (1) el coste de TMDB es *condicional* —solo aparece
> al monetizar— mientras que el de migrar es cierto e inmediato: tres semanas
> de trabajo, datos de cine peores y un motor de siembra reconstruido; (2) el
> tramo gratuito (<50.000 $/año) **no es autoservicio**: exige la modalidad
> "Negotiated Contract", que entra en cola de revisión comercial, así que no es
> un tier sobre el que se pueda planificar.

- **Por qué**: TMDB prohíbe el uso comercial bajo licencia gratuita
  (149 $/mes desde el primer euro). TheTVDB escala por facturación propia:
  **gratis por debajo de 50.000 $/año**, 1.000 $/año hasta 250 k$,
  10.000 $/año hasta 1 M$.
- **Modalidad de clave**: pedir la **licenciada**. La alternativa
  ("user-supported") exige que cada usuario final mantenga una suscripción de
  12 $/año — inviable para un producto de consumo.
- **Base URL**: `https://api4.thetvdb.com/v4`
- **Auth**: `POST /login` devuelve un JWT que **dura un mes**. El cliente debe
  renovarlo solo (mismo patrón que el cliente Twitch/IGDB actual en
  `backlogg/games/adapters/igdb.py`).
- **Atribución obligatoria**: enlace directo a TheTVDB.com visible para el
  usuario que ve los metadatos.

- **Endpoints relevantes**:
  - `GET /movies/{id}` · `GET /movies/{id}/extended` (créditos, artwork)
  - `GET /movies/slug/{slug}` · `GET /movies/{id}/translations/{language}`
  - `GET /series/{id}` · `/extended` · `/artworks` · `/slug/{slug}` ·
    `/translations/{language}` · `/episodes/{season-type}`
  - `GET /search`, `GET /search/remoteid/{remoteId}`, `GET /genres`,
    `GET /people/{id}`, `GET /updates`

- **⚠️ No existe endpoint de "similar" ni de "trending".** Ambos se sustituyen
  por cálculo local — features 80 y 81, ver `docs/recommendations-plan.md`.

- **⚠️ No existe feed de popularidad paginado.** Es el problema caro: obligaría
  a rehacer `scheduler/jobs.py` y `scripts/backfill_sync.py`, no solo a cambiar
  de adaptador. Las dos únicas vías, ambas con pegas:

  | Vía | Ordena por popularidad | Pagina | Pega |
  |---|---|---|---|
  | `GET /movies?page=N` · `GET /series?page=N` | ❌ (orden de id) | ✅ | Hay que recorrer la base entera y rankear localmente por `score` |
  | `GET /movies/filter` · `GET /series/filter` | ✅ (`sort=score`) | ❌ | `country` **y** `lang` son obligatorios: obliga a fan-out por pares país/idioma |

  El campo `score` está presente en casi todas las entidades y, según el propio
  swagger, «se usa para insinuar popularidad relativa a efectos de ordenación»,
  sin garantías sobre su significado exacto.

- **Otros límites**: `GET /search` está limitado a 5.000 resultados máximo.
- **Slugs**: TheTVDB expone slug propio (`/movies/slug/{slug}`), pero el
  catálogo **genera los suyos** con `_slugify(titulo)-año` en el adaptador.
  Mantenerlo así: es lo que permite que las URLs sobrevivan al cambio de
  fuente sin perder posicionamiento.
- **external_ids source value**: `THETVDB`

## RAWG — EVALUADA Y APARCADA (2026-08-29)

> **No se usa.** Se evaluó como sustituto de IGDB y se descartó por coherencia
> con la decisión sobre TMDB: el coste de IGDB también es condicional, y migrar
> antes de tener usuarios gasta el recurso escaso (tiempo hasta el lanzamiento)
> para cubrir un problema que solo existe si el producto funciona. La
> investigación se conserva: RAWG es la salida natural si los términos
> comerciales de IGDB —que no publican precio— acaban siendo un problema.

- **Base URL**: `https://api.rawg.io/api` · **Auth**: `key` como query param.
- **Cuota gratuita con uso comercial permitido**: 20.000 peticiones/mes,
  siempre que el proyecto tenga menos de 100.000 usuarios activos o 500.000
  páginas vistas al mes. Planes Business (50.000) y Enterprise por encima.
- **Atribución obligatoria**: enlace activo a RAWG **desde cada página** donde
  se usen sus datos. Más estricto que TMDB, que se conformaba con el "acerca
  de" — condiciona el diseño de la ficha de juego.
- **Sin ventana de caducidad de caché** en sus términos (a diferencia de los
  6 meses de TMDB).

- **Presupuesto de peticiones — la clave del diseño**: `GET /games` devuelve
  **40 ítems por página** (`page_size` máximo) con ordenación por popularidad
  (`ordering=-added` o `-rating`). Sembrar 10.000 juegos cuesta **250
  peticiones, no 10.000**.

  | Campo del modelo `Game` | ¿En el listado? |
  |---|---|
  | title, slug, release_date | ✅ |
  | poster_url (`background_image`) | ✅ |
  | rating_external, rating_count_external | ✅ |
  | genres, platforms | ✅ |
  | **overview** (`description`) | ❌ solo en `GET /games/{id}` |
  | **companies** (developers/publishers) | ❌ solo en `GET /games/{id}` |

  Los dos campos que faltan se resuelven con el **fallback on-demand** que ya
  existe en `backlogg/games/service.py`: una petición por ficha, la primera vez
  que alguien la abre, pagada una sola vez.

- **⚠️ No hay equivalente a `game_type` de IGDB**, así que el *category
  allowlist* de la feature 65 (`backlogg/games/constants.py`) no se puede
  portar tal cual. Sustituirlo por otro filtro de calidad (umbral de
  `ratings_count` o `added`).
- **external_ids source value**: `RAWG`

- **Alternativas descartadas**: Giant Bomb (solo uso no comercial, revocan la
  clave), MobyGames (de pago y con límites de ritmo muy bajos: 720
  peticiones/hora en el tier no comercial).

## SMTP (Email) — feature 36 `account_recovery`

- **Transporte**: SMTP genérico vía la stdlib (`smtplib` +
  `email.message.EmailMessage`), sin dependencias externas.
- **Uso**: emails transaccionales de verificación de cuenta y reset de password.
- **Flujo**: `smtplib.SMTP(host, port)` → `starttls()` si `SMTP_STARTTLS` →
  `login(user, pass)` si hay credenciales → `send_message` (text + HTML
  alternativo). Envío síncrono ejecutado en un thread (`asyncio.to_thread`).
- **Aislamiento**: detrás de una interfaz `EmailSender`. Con `SMTP_HOST`
  presente envía vía SMTP; sin él, un fallback loguea el enlace y no envía —
  así dev y CI arrancan sin servidor de correo.
- **Pruebas**: Gmail con App Password (2FA; `smtp.gmail.com:587` STARTTLS;
  remitente = tu gmail; ~500 envíos/día). Producción con dominio propio: solo
  cambian las variables `SMTP_*`.
- **Seguridad**: `SMTP_PASSWORD` es secret — nunca en logs ni en respuestas de error.

## Environment variables

| Variable               | Used by       | Description                                      |
|------------------------|---------------|--------------------------------------------------|
| `DATABASE_URL`         | SQLAlchemy    | PostgreSQL connection string (Neon in production)|
| `TEST_DATABASE_URL`    | pytest        | PostgreSQL DB de test (separada de la de dev)    |
| `TMDB_API_KEY`         | TMDB client   | Bearer token for TMDB API                        |
| `TWITCH_CLIENT_ID`     | IGDB client   | Twitch app client ID                             |
| `TWITCH_CLIENT_SECRET` | IGDB client   | Twitch app client secret                         |
| `SEED_TOP_N_MOVIES`    | — | **INERTE desde la feature 86.** El catálogo de movies lo define `TMDB_SEED_MIN_VOTES_MOVIES`, no un número de ítems. Se conserva porque Render y el workflow de backfill la exportan (default: 100) |
| `SEED_TOP_N_SERIES`    | — | **INERTE desde la feature 86**, ídem (default: 100) |
| `SEED_TOP_N_BOOKS`     | Sync job      | How many books to seed (default: 100)            |
| `SEED_TOP_N_GAMES`     | Sync job      | How many games to seed (default: 100)            |
| `TMDB_SEED_MIN_VOTES_MOVIES` | Enumeración TMDB | Umbral `vote_count.gte` que define el catálogo de películas (default: 25 → 57.135 movies) |
| `TMDB_SEED_MIN_VOTES_SERIES` | Enumeración TMDB | Ídem para series (default: 25 → 10.880 series) |
| `TMDB_SEED_START_YEAR` | Enumeración TMDB | Primer año de estreno a enumerar (default: 1874, el más antiguo de TMDB) |
| `TMDB_SEED_END_YEAR`   | Enumeración TMDB | Último año; vacío = año actual + 1 (TMDB ya trae estrenos futuros fechados) |
| `TMDB_SEED_CONCURRENCY`| Enumeración + hidratación TMDB | Peticiones TMDB en vuelo (`Semaphore`). Default 8 ≈ 32 req/s frente al límite de ~50 |
| `TMDB_SEED_MAX_ATTEMPTS`| Hidratación TMDB | Pasadas **concluyentes** que recibe un target antes de retirarse de la lista de trabajo como no enlazable (default: 3). Una petición fallida no cuenta, así que una caída de TMDB no retira targets sanos |
| `BOOKS_SEED_MIN_READINGLOG`    | Open Library seed | Mínimo `readinglog_count` del stream inglés (default: 20 → 16.959 obras) |
| `BOOKS_SEED_MIN_READINGLOG_ES` | Open Library seed | Ídem para el stream en castellano; la señal es ~10× menor, por eso es distinto (default: 5 → 1.858 obras) |
| `BOOKS_SEED_MIN_PAGES`         | Open Library seed | Mínimo `number_of_pages_median`; descarta folletos (default: 100) |
| `BOOKS_SEED_MIN_EDITIONS`      | Open Library seed | Mínimo `edition_count` del stream inglés: el filtro de notoriedad que separa la entrega suelta de la obra canónica (default: 10) |
| `BOOKS_SEED_MIN_EDITIONS_ES`   | Open Library seed | Ídem para el stream en castellano. **No subir a 3**: *Reina roja* tiene exactamente 2 ediciones (default: 2) |
| `BOOKS_SEED_ES_EVERY_N`        | Open Library seed | Una obra en castellano cada N huecos sembrados; 0 desactiva el stream ES (default: 10) |
| `SYNC_SLICE_SIZE`      | Sync job      | Max items per sync run and type (default: 200)   |
| `SYNC_SLICE_SIZE_MOVIES` / `_SERIES` / `_BOOKS` / `_GAMES` | Sync job | Override por tipo del anterior. Movies necesita ~350/noche y series ~61 para la ventana de 6 meses de TMDB (default: sin valor → cae al global) |

### Roadmap — variables planificadas (features 35-40)

Aún no leídas por el código; se añaden cuando se implemente cada feature.

| Variable                              | Feature | Description                                                        |
|---------------------------------------|---------|-------------------------------------------------------------------|
| `SMTP_HOST`                           | 36      | Host SMTP; vacío → `EmailSender` cae a log (no envía)             |
| `SMTP_PORT`                           | 36      | Puerto SMTP (default 587, STARTTLS)                               |
| `SMTP_USERNAME` / `SMTP_PASSWORD`     | 36      | Credenciales SMTP; `SMTP_PASSWORD` es secret (nunca en logs)      |
| `SMTP_FROM_EMAIL`                     | 36      | Dirección remitente del email                                    |
| `SMTP_STARTTLS`                       | 36      | Usar STARTTLS antes del login/envío (default true)               |
| `APP_BASE_URL`                        | 36      | Base para construir los enlaces de verificación/reset             |
| `REFRESH_EXPIRE_DAYS`                 | 35      | Vida del refresh token (el access `JWT_EXPIRE_MINUTES` pasa a corto)|
| `RATE_LIMIT_AUTH` / `RATE_LIMIT_DEFAULT` | 37   | Límites de peticiones por ventana (auth y general)                |
| `SENTRY_DSN`                          | 38      | DSN de Sentry; ausente = integración desactivada, sin overhead    |
| `LOG_LEVEL`                           | 38      | Nivel del logging estructurado (default `INFO`)                   |
