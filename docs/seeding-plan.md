# Plan de siembra del catálogo de producción

> Investigación de 2026-09-02. **Decisión tomada: el catálogo se define por un
> umbral de calidad (`vote_count ≥ 25` en TMDB), no por un número de ítems.**
>
> | Tipo | Ítems | Criterio |
> |---|---|---|
> | Movies | **57.135** | `vote_count ≥ 25` |
> | Series | **10.880** | `vote_count ≥ 25` |
> | Books | **18.874** | Filtro de la feature 73, sin cambios |
> | Games | **31.958** | Filtro de la feature 65, sin cambios |
> | **Total** | **~118.850** | |
>
> Todas las cifras están **medidas contra las fuentes reales** el 2026-09-02, no
> estimadas: `total_results` de `/discover` en TMDB, `/games/count` en IGDB y
> `numFound` de `search.json` en Open Library.

Este documento responde a tres preguntas: **cuánto** se puede llenar, **cómo** se
llena la primera vez, y **cómo** se mantiene al día después. La referencia de
endpoints y límites de cada proveedor vive en `docs/external-apis.md`.

---

## 1. Por qué el método actual no llega

> ✅ **Resuelto para movies y series por la feature 86.** Los tres defectos de
> abajo eran del recorrido por offset de `/popular`, que ya no está en el
> camino de la siembra: `sync_movies`/`sync_series` se alimentan de la lista
> objetivo de `seed_targets` (§3). Se conserva el diagnóstico porque es lo que
> justifica el diseño y lo que evita que alguien lo deshaga por comodidad.
> Books y games nunca tuvieron este problema: su enumeración no es un ranking
> de popularidad.

### Techo duro de 10.000 por tipo

`get_top_movies` / `get_top_series` paginan `/movie/popular` y `/tv/popular`.
**TMDB corta la paginación en la página 500**, y devuelve 20 ítems por página:
10.000 ítems y ni uno más (ya anotado en `backlogg/movies/adapters/tmdb.py:144`).

`SEED_TOP_N_*` está hoy en 10000 (`docs/operations.md`). Eso no es una elección
de producto: **es exactamente el techo del método**.

### El recorrido por offset no es estable

`/movie/popular` se reordena continuamente. Un ítem que estaba en la página 30
cuando el cursor iba por la 12 puede estar en la 28 cuando el cursor llega, y
entonces no se visita nunca. El cursor de `sync_cursors` avanza sobre un conjunto
que se mueve bajo sus pies, así que **ni siquiera garantiza cubrir los 10.000**.

### `popularity` no es una señal de calidad

Éste es el hallazgo que define todo el plan. Se muestrearon 40 películas por
banda de puesto en el ranking de `popularity` y se pidió su `vote_count` real:

| Banda de puestos | `vote_count` mediana | % con ≥50 votos |
|---|---|---|
| 1–2.000 | 4.779 | 92% |
| 2.000–5.000 | 1.173 | 92% |
| 5.000–10.000 | 77 | 52% |
| 10.000–20.000 | **4** | 38% |
| 20.000–40.000 | 3 | 30% |
| 40.000–70.000 | 4 | 25% |
| 70.000–100.000 | 1 | 10% |

Dos lecturas, y la segunda es la importante:

1. El acantilado de calidad está entre el puesto 5.000 y el 10.000. Ordenar por
   `popularity` y cortar por número de ítems mete grabaciones de teatro regional
   y cortos sin ficha en cuanto se pasa de ahí.
2. **Pero un 30% de las películas del puesto 20.000–40.000 tiene ≥50 votos.**
   `popularity` es una métrica de interés reciente, no de notoriedad: cortar por
   puesto tira miles de películas legítimamente conocidas.

Por eso el catálogo **no se define por un número de ítems sino por un umbral de
`vote_count`**, y el número de ítems sale de ahí.

### 3,1 s por ítem

Medido sobre el run real 32937145403 (5 h 11 min, 6.000 series, 0 errores):
`18.676 s / 6.000 = 3,1 s por ítem`, todo secuencial. Por ítem:

- 2 llamadas HTTP (detail + credits)
- ~7 credits × `_get_or_create_person_tmdb`, que hace `get_person_id_by_external`
  **y** `get_person_by_id` como dos queries separadas
  (`backlogg/movies/service.py:62-64`), más `upsert_person`
  (execute + flush + select) y `upsert_external_id` si la persona es nueva, más
  `upsert_credit`
- 2 commits

Son **entre 35 y 75 round trips a Neon por ítem**, uno detrás de otro. A ~40 ms
cada uno salen 1,6–2,5 s solo de latencia SQL. El cuello **no es el rate limit de
TMDB, es el chattiness contra la base de datos**. Por eso subir `--slice-size`
nunca sirvió de nada: el coste es por ítem, no por iteración.

---

## 2. Dimensionado

### 2.1 Cuánto hay en cada fuente

**TMDB por umbral de `vote_count`** (`total_results` de `/discover`, exacto):

| `vote_count ≥` | Movies | Series |
|---|---|---|
| 10 | 105.336 | 19.358 |
| **25 (elegido)** | **57.135** | **10.880** |
| 50 | 36.317 | 6.883 |
| 100 | 23.275 | 4.354 |
| 200 | 14.867 | 2.538 |
| 500 | 8.064 | 1.148 |

Nota de calibración: **TMDB no tiene 100.000 series que le importen a nadie.**
Solo 19.358 superan los 10 votos. Cualquier objetivo de series por encima de
~20.000 es aritméticamente imposible sin meter ruido puro.

**Books y games** se quedan con los filtros de calidad que ya tienen, y su tamaño
es el que esos filtros entregan:

- **Books** (feature 73): `readinglog_count ≥ 20` y `edition_count ≥ 10` en
  inglés, `≥ 5` y `≥ 2` en castellano, más `number_of_pages_median ≥ 100`.
  `numFound` real: **17.015 en inglés + 1.859 en castellano = 18.874**.
  El comentario de `backlogg/core/config.py:23` («comfortably above
  `SEED_TOP_N_BOOKS`») se escribió con el default de 100 y hay que corregirlo al
  subir el objetivo.
- **Games** (feature 65): allowlist de `game_type` **y `rating > 0`**.
  `/games/count` real: 374.223 juegos en total, 336.653 pasan la allowlist, pero
  solo **31.958** tienen valoración. Quitar `rating > 0` los multiplicaría por
  diez metiendo ~300.000 juegos sin ninguna valoración, que es justo el ruido que
  el filtro existe para excluir.

### 2.2 Almacenamiento — no es limitante

Medido sobre la DB de dev (1.495 ítems de catálogo):

| Concepto | Bytes/fila | Filas por ítem | Bytes/ítem |
|---|---|---|---|
| Fila del ítem | ~1.100 | 1 | 1.100 |
| `catalog_search` (vista materializada + índices) | 1.959 | 1 | 1.959 |
| `credits` | 330 | ~7 | 2.310 |
| Joins de géneros/plataformas | ~150 | ~3 | 450 |
| **Total por ítem** | | | **~6 KB** |

Para ~119.000 ítems: **~715 MB** de catálogo más ~220 MB de `people` y sus
`external_ids` = **~1 GB**. A 0,35 $/GB-mes de Neon son **~0,35 $/mes**. Con los
embeddings de la feature 75 encima (119k × 512 dims × 4 B más índice HNSW ≈
600 MB) se queda en **~0,56 $/mes**. No condiciona nada.

### 2.3 Ventana de caché de TMDB — obliga a subir el slice de movies

TMDB prohíbe cachear sus datos más de **6 meses**, así que sus ítems deben
re-sincronizarse enteros cada 180 días. La obligación aplica **solo a movies y
series**: Open Library es CC0 y los términos de IGDB no imponen ventana.

| | Ítems | Por noche para cubrir 180 días | `SYNC_SLICE_SIZE` hoy |
|---|---|---|---|
| Movies | 57.135 | **318** | 200 ❌ |
| Series | 10.880 | 61 | 200 ✅ |

**Movies no cabe.** Hace falta subir su slice a ~350-400. A 3,1 s/ítem eso son
~18-20 min, por encima del tope de ~15 min de una request a Render; con la ruta
de escritura por lotes (§4) bajan a ~1-2 min.

Dos consecuencias concretas:

1. La feature 84 (`bulk_load_pipeline`) es **necesaria**, no opcional.
2. `SYNC_SLICE_SIZE` es hoy **global**. Como movies necesita ~350 y series 61,
   hace falta que sea **configurable por tipo**. Recomendación adicional: mover el
   nocturno del endpoint de Render al script directo contra Neon, que quita
   Render del camino crítico del todo.

### 2.4 GitHub Actions — gratis

El repositorio es **público**, así que los minutos de Actions son ilimitados. El
único límite operativo es el de **6 h por job**, y la siembra cabe de sobra (§5).

### 2.5 Conclusión

**Ni el coste ni la infraestructura limitan nada a esta escala.** Los límites
reales son dos: el techo de 10.000 del método de enumeración actual (§3 lo
resuelve) y la ventana de 6 meses de TMDB para movies (§2.3 lo resuelve).

---

## 3. Cómo se enumera cada fuente

El cambio de fondo es **separar la enumeración de la hidratación**. Hoy están
fundidas en el cursor de `/popular`, y de ahí vienen el techo, la inestabilidad
del recorrido y la imposibilidad de saber qué falta.

### TMDB — `/discover` con `vote_count.gte`, troceado por año

> ✅ **Implementado en la feature 86.** Lo que sigue describe el código real:
> `backlogg/scheduler/discovery.py` (troceo y guardia),
> `TMDBClient.discover_movies_page` / `TMDBSeriesClient.discover_series_page`
> (paginación cruda) y `scripts/seed_tmdb_targets.py` (CLI).

```
GET /discover/movie?page=N
    &include_adult=false&include_video=false
    &sort_by=primary_release_date.asc
    &vote_count.gte=25
    &primary_release_date.gte=YYYY-01-01&primary_release_date.lte=YYYY-12-31
```

Para series el campo de fecha es `first_air_date` y el orden
`first_air_date.asc`; `/discover/tv` no tiene `include_video` ni expone
contenido adulto por esta vía, así que los dos flags son solo de movies.

El `sort_by` por fecha es deliberado: ordenar por popularidad reintroduciría
el defecto que hunde a `/popular`, que se reordena mientras se pagina.

`/discover` tiene el mismo tope de 500 páginas que `/popular`, **pero troceando
por año de estreno ninguna rebanada se acerca**. Medido con `vote_count ≥ 25`:

| Año | Movies | Series |
|---|---|---|
| 2016 | 1.997 | 474 |
| 2018 | 2.126 | — |
| 2019 | **2.175** (máximo observado) | 596 |
| 2022 | 1.831 | **752** (máximo observado) |
| 2024 | 1.406 | 569 |

El peor año usa el 22% del cupo de 10.000. Hay **4× de margen**, suficiente para
bajar el umbral más adelante sin rediseñar nada.

**La guardia del tope es explícita, no una suposición.** El orquestador lee
`total_pages` de la primera página de cada ventana:

1. Si el año la supera → se trocea en sus **doce meses** y se enumeran uno a uno
   (un mes lleva ~1/12 de los ítems, así que el año tendría que traer >60.000
   para que un mes también se pasara).
2. Si un mes *aun así* la supera → **el run no aborta**. Enumera las 500 páginas
   que TMDB sirve y marca la ventana en `EnumerationStats.truncated_windows`;
   el script sale con **código 2** y un `logger.error` con las etiquetas
   afectadas. Tirar una pasada entera de siembra por una ventana mala sería
   peor; encogar el catálogo en silencio, mucho peor todavía.

Esto enumera el **conjunto objetivo exacto y completo**, sin techo, sin descargar
1,18 M de IDs para descartar el 95%, y de forma reproducible: mismos parámetros →
misma lista.

**Limitación conocida:** un ítem sin fecha de estreno no cae en ninguna ventana
y no se enumera. Con `vote_count ≥ 25` es residual, y esos ítems siguen
entrando por el fallback on-demand y por el fan-out de búsqueda.

#### La lista objetivo se persiste: `seed_targets`

La enumeración **no hidrata nada**: escribe en la tabla `seed_targets`
(`item_type, source, external_id, vote_count, release_year, attempts, ...`,
esquema completo en `docs/schema.md`). Cada página se persiste según llega, así
que una enumeración interrumpida conserva todo lo que ya había enumerado.

Lo pendiente **no es un offset**, es una diferencia contra el catálogo:

```sql
seed_targets LEFT JOIN external_ids USING (item_type, source, external_id)
WHERE external_ids.id IS NULL
  AND unreachable_at IS NULL              -- no retirado por 404
  AND attempts < TMDB_SEED_MAX_ATTEMPTS   -- no retirado por no enlazable
ORDER BY attempts ASC, vote_count DESC NULLS LAST, id ASC
```

Un run que muera a mitad no deja estado que reconciliar. El orden por
`vote_count` hace que una siembra interrumpida deje dentro lo mejor del
catálogo.

#### Retirada de targets inalcanzables — por qué `pending` converge

Hay dos motivos, sin relación entre sí, por los que un target puede **no
enlazarse nunca**:

1. **404 en TMDB.** El id se enumeró pero TMDB ya no lo sirve (borrado o
   fusionado con otra ficha).
2. **Resuelve bien y aun así no se enlaza.** El detalle se descarga sin
   error y el ítem no acaba con fila en `external_ids`. Caso realista: la
   colisión de slug — `slug` es único, así que dos ids de TMDB con el mismo
   título y año comparten una sola fila y solo uno conserva su enlace.
   Hasta la migración `0036` la causa masiva era otra: `uq_external_id` no
   incluía `item_type` y un id de persona bastaba para bloquear la película o
   serie con el mismo número (issue #20). Eso ya está arreglado.

Si esos targets se quedan en el conjunto pendiente, `pending` tiene un **suelo
permanente > 0**. Y las dos garantías del diseño dependen de que `pending`
llegue a 0: la rotación de refresco solo se dispara cuando no queda nada
pendiente, y el bucle de `scripts/backfill_sync.py` solo termina cuando no queda
nada pendiente. Con un suelo del orden de miles frente a una rebanada de ~61 en
series, la rotación **no volvería a ejecutarse jamás** y el backfill giraría
gastando peticiones a TMDB sin progresar.

Por eso se **retiran**, no solo se reordenan:

- El 404 se sella en `unreachable_at` **la primera vez** que se observa. Es una
  respuesta definitiva: volver a preguntar no la cambia.
- El target que resuelve bien y sigue sin enlazarse se retira tras
  `TMDB_SEED_MAX_ATTEMPTS` pasadas **concluyentes** (default 3). Una petición
  que *falla* no cuenta como pasada, así que una caída de TMDB no puede retirar
  un target sano.

El residuo **no desaparece de la vista**: se cuenta aparte y se reporta como
`stuck` (desglosado en `gone` y `unlinkable`) en el resultado del job, en su
log —con un `warning` explícito si hay `unlinkable`— y en el resumen del script
de enumeración. Un catálogo que no converge es justo lo que el operador
necesita poder ver, venga el atasco de donde venga.

> El defecto de fondo (`uq_external_id` global entre tipos) era
> **preexistente** y quedó fuera del alcance de esta feature; se arregló
> después, en la migración `0036` (issue #20), que además reabrió los targets
> que había retirado. La retirada sigue siendo necesaria para el 404 y para la
> colisión dentro de un mismo tipo. Ver `docs/schema.md`.

#### Rotación de refresco

Cuando no quedan targets pendientes **trabajables** —lo que es alcanzable
gracias a la retirada de arriba—, la rebanada nocturna se llena con los ítems
del catálogo de **`last_synced_at` más antiguo**. Sin esto, retirar el cursor de
`/popular` habría *perdido* algo que el recorrido daba por efecto colateral: la
cobertura de la ventana de caché de 6 meses de TMDB (§2.3). La rotación
explícita es la misma garantía, dicha directamente en vez de emerger de un
ranking.

#### `SEED_TOP_N_MOVIES` / `SEED_TOP_N_SERIES`

Dejan de ser el criterio de corte y quedan **inertes**. El catálogo lo define
`TMDB_SEED_MIN_VOTES_*`; el tamaño de la rebanada nocturna,
`SYNC_SLICE_SIZE_*`. Se conservan (en vez de borrarse) porque Render y
`.github/workflows/backfill-sync.yml` siguen exportándolas, y quitar un nombre
que los despliegues declaran se leería como un descuido. `SEED_TOP_N_BOOKS` y
`SEED_TOP_N_GAMES` siguen vivas: sus enumeraciones no cambian.

### TMDB — los ficheros diarios de IDs son para el incremental

```
https://files.tmdb.org/p/exports/movie_ids_MM_DD_YYYY.json.gz
https://files.tmdb.org/p/exports/tv_series_ids_MM_DD_YYYY.json.gz
```

JSONL comprimido (28 MB y 5 MB el 2026-09-02), un objeto por línea con `id`,
`original_title`/`original_name`, `popularity`, `adult` y `video`. Publicados a
diario: el job arranca ~07:00 UTC y todo está disponible a las 08:00 UTC; se
conservan 3 meses. Las entradas `adult` van en ficheros `adult_*` aparte, así que
el filtro relevante en el fichero normal es `video=true` (62.264 entradas en
movies el 2026-09-02).

**No son la fuente de la siembra** — no traen `vote_count`, así que no permiten
aplicar el criterio de calidad. Su papel es el **diff diario para detectar
altas** (§6).

### Open Library — dumps mensuales

| Fichero | Tamaño | Para qué |
|---|---|---|
| `ol_dump_works_latest.txt.gz` | ~2,9 GB | La obra: título, autores, descripción |
| `ol_dump_authors_latest.txt.gz` | ~0,5 GB | Autoría (rol `AUTHOR`) |
| `ol_dump_ratings_latest.txt.gz` | ~5 MB | Señal de notoriedad |
| `ol_dump_editions_latest.txt.gz` | ~9,2 GB | **Ver aviso** |

Formato TSV con columnas `type, key, revision, last_modified, JSON`. Descarga
desde `openlibrary.org/data/`, o por torrent desde `archive.org/details/ol_exports`.
Sacar `search.json` del camino crítico elimina de golpe los 500 intermitentes que
costaron el issue #9 y el presupuesto de retries que hubo que montar.

> ⚠️ **`ddc` y `lcc` viven en los registros de *edition*, no en los de *work*.**
> La feature 72 los obtiene de `search.json`, donde Solr los agrega desde las
> ediciones. Para mantener ese criterio con dumps hace falta también
> `ol_dump_editions_latest` (~9,2 GB) — del que, como beneficio secundario, sale
> `edition_count` contando directamente, que es el discriminante de notoriedad de
> la feature 73. Es el único punto pesado de todo el plan.
>
> Alternativa si 9,2 GB resulta inmanejable: enumerar y clasificar desde works, y
> pedir `ddc`/`lcc` a `search.json` solo para los seleccionados. Sigue siendo una
> llamada por ítem, pero sobre 18.874 y no sobre el catálogo entero.

### IGDB — nada que cambiar

`get_top_games` ya trae **500 juegos con todos los campos en un solo request**
(`backlogg/games/adapters/igdb.py:137-162`), a 4 req/s, sin llamada de detalle por
ítem. Los 31.958 juegos son 64 requests: **~16 segundos**.

Los dumps de IGDB (`GET /v4/dumps`) existen pero son **solo para partners**, y no
hacen falta.

---

## 4. Cómo se hidrata y se escribe

### Una petición por ítem en vez de dos (solo TMDB)

> ✅ **Implementado en la feature 86.**

TMDB no tiene endpoint bulk de detalle: la hidratación es 1 petición por ítem,
inevitablemente. Pero eran **dos** — `/movie/{id}` y `/movie/{id}/credits`. Con
[`append_to_response`](https://developer.themoviedb.org/docs/append-to-response)
es una sola:

```
GET /movie/{id}?append_to_response=credits,external_ids
GET /tv/{id}?append_to_response=credits,external_ids
```

Mitad del HTTP, y encaja directamente con la feature 74: `SOURCE_AUTHOR` sale del
mismo payload sin ninguna petición adicional (por eso se pide `external_ids`
aunque todavía no se lea).

Dos consecuencias que conviene tener presentes:

- **En series el cambio además añade información**: los créditos `CREATOR`
  vienen de `created_by`, que vive en el detalle y **no** en
  `/tv/{id}/credits`. La petición única es estrictamente más informativa que
  las dos que sustituye.
- **En el job nocturno ya no existe un fallo independiente de credits.** Si la
  petición falla, falla el ítem y cuenta en `errors`. `people_errors` sigue
  vivo, pero ahora solo recoge fallos de *escritura* de people/credits. Los
  caminos on-demand y el backfill dirigido (feature 85) siguen usando
  `/movie/{id}/credits` porque ahí la fila ya existe y solo faltan los credits.

### Paralelizar

> ✅ **Implementado en la feature 86.**

`asyncio.gather` + `Semaphore`, el patrón que ya usa el fan-out de búsqueda
(`backlogg/search/service.py`, `Semaphore(5)`). El límite documentado de TMDB
ronda las 50 req/s: conviene quedarse en 30-40 y no apurar, así que
`TMDB_SEED_CONCURRENCY` va a **8** por defecto (≈32 req/s con el RTT medio de
TMDB) y gobierna tanto las páginas de `/discover` como la hidratación.

En la enumeración las **ventanas se recorren en serie** y son las *páginas de
dentro* las que van en paralelo: al revés, la enumeración entera estaría en
vuelo a la vez y el número de peticiones simultáneas dependería del número de
años, no del semáforo. En la hidratación el fetch es paralelo y la **escritura
secuencial** — `AsyncSession` no es segura en concurrencia.

### Escribir por lotes — esto es lo que de verdad importa

Nada de lo anterior sirve si se escribe a 3,1 s/ítem. La carga tiene que ser:

- `COPY` a tablas temporales + `INSERT ... SELECT ... ON CONFLICT` por lotes, en
  lugar de commit por ítem.
- Resolver todas las personas de un lote con **un** `SELECT ... WHERE external_id
  IN (...)` y escribir con inserts multi-fila, en lugar de 2 queries por persona.

Pasa de ~40 round trips por ítem a ~4 por lote de 1.000. Es el cambio con más
impacto del plan y es **prerrequisito de los demás**.

---

## 5. Presupuesto de la siembra inicial

| Tipo | Ítems | Peticiones de enumeración | Peticiones de hidratación |
|---|---|---|---|
| Movies | 57.135 | ~2.900 (`/discover` × año, 20/página) | 57.135 |
| Series | 10.880 | ~600 | 10.880 |
| Books | 18.874 | 4 descargas de dump | 0 |
| Games | 31.958 | 64 | 0 |
| **Total** | **~118.850** | **~3.600** | **68.015** |

Tiempos estimados:

- Enumeración TMDB: ~3.600 peticiones a 30 req/s → **~2 min**.
- Hidratación TMDB: 68.015 peticiones a 30-40 req/s → **~30-38 min**.
- Books: descarga y parseo en streaming de los dumps → **~30-60 min** (dominado
  por los 9,2 GB de editions).
- Games: 64 requests a 4 req/s → **~16 s**.
- Escritura con `COPY`: minutos.

**Total: ~1-1,5 h en un solo job de GitHub Actions** (tope 6 h, minutos gratis
por ser repo público). Frente a las **~102 h** que costaría el mismo catálogo al
ritmo actual de 3,1 s/ítem.

Aun así conviene **partir el workflow en una matrix por tipo**: cuatro jobs en
paralelo, cada uno con su margen frente al tope de 6 h, y un fallo en books no
tumba la siembra de movies.

### 5.1 Qué mirar mientras corre (panel de instrumentos)

Una siembra dura horas. Los contadores que devuelve cada tramo son la única
forma de saber si se está perdiendo catálogo **antes** de que la carga termine;
cuando acaba, ya está horneada. Los tres que hay que leer en cada iteración del
log de `scripts/backfill_sync.py` (y en la respuesta de
`POST /v1/admin/sync/{type}`):

| Contador | Qué significa | Qué hacer si sube |
|---|---|---|
| `errors` | Ítems que fallaron y no se escribieron | Si `synced == 0` y `errors > 0` el backfill aborta solo. Si convive con `synced` alto, mirar el log del ítem concreto |
| `people_errors` | El ítem se guardó pero sus credits no | No aborta el tramo (un credit ausente no puede tumbar la slice). Se recupera después con `backfill_sync.py --only-missing-credits` |
| `skipped_links` | El ítem se guardó **sin enlace en `external_ids`**: la terna `(item_type, source, external_id)` ya la tenía otro ítem del mismo tipo (issue #22) | **Es el que importa durante la siembra.** Cada unidad es una fila del catálogo que ya no se encontrará por id externo, no se refrescará nunca y puede duplicarse. Si crece tramo a tramo hay un fallo sistemático: parar y mirar los `WARNING` de `backlogg.shared.external_ids`, que nombran la terna, el ítem pretendiente y el que ya la tiene |

`skipped_links` **no** cuenta las re-escrituras idempotentes del mismo enlace al
mismo ítem (la misma persona en cast y crew, un tramo re-ejecutado): esas son
normales y contarlas convertiría el número en ruido. Solo cuenta el robo de
enlace entre dos ítems distintos.

Por qué está aquí y no en un panel aparte: el mismo mecanismo ciego produjo los
issues #7, #15 y #20, y en los tres casos los datos se perdieron durante meses
y el hallazgo fue accidental, en una QA que casualmente comparaba lo enumerado
contra lo enlazado.

Lo que estos contadores **no** cubren todavía: `seed_targets` da por convergido
un target si existe *alguna* fila con su terna, sin mirar a qué `item_id`
apunta, así que un target robado se cuenta como hecho y no aparece en `stuck`.
Arreglarlo obliga a decidir qué `item_id` es el dueño legítimo — decisión de
datos, no de instrumentación.

---

## 6. Mantenimiento: estrenos y publicaciones

El incremental **no es re-recorrer `/popular`**. Cada fuente tiene su mecanismo
nativo:

| Fuente | Novedades | Actualizaciones |
|---|---|---|
| **TMDB** | Diff del fichero diario de IDs contra el estado local → IDs nuevos | [`/movie/changes` y `/tv/changes`](https://developer.themoviedb.org/reference/changes-movie-list): IDs cambiados, ventana máxima de **14 días**, 100 por página |
| **Open Library** | Diff del dump mensual, o `/recentchanges` | Igual |
| **IGDB** | `where created_at > <última ejecución>` en la propia query | `where updated_at > <última ejecución>` |

> ⚠️ **Un estreno no tiene votos el día que sale.** El incremental no puede usar
> `vote_count ≥ 25` como puerta de entrada o no entraría ninguna novedad jamás.
> Hacen falta dos caminos separados:
>
> - **Alta inmediata de estrenos por fecha**, para que el catálogo tenga las
>   novedades desde el día uno.
> - **Barrido periódico de promoción**: ítems que estaban por debajo del umbral y
>   lo han cruzado. `/discover` con `vote_count.gte=25` sobre los últimos años,
>   comparado con lo que ya está en el catálogo, resuelve esto sin estado extra.
>
> Sin el segundo camino el catálogo se congela: una película de 2019 que gane
> tracción en 2027 no entraría nunca.

Volumen diario real: unos pocos cientos de ítems.

---

## 7. Orden de implementación

| # | Feature | Por qué en este orden |
|---|---|---|
| 1 | **84 `bulk_load_pipeline`** (`COPY` + upserts agrupados) ✅ | Prerrequisito de todo. Sin esto ningún método de enumeración sirve, es condición necesaria para la ventana de 6 meses de movies (§2.3), y además arregla el backfill dirigido a huecos (issue #15) |
| 2 | **85 `backfill_credits_targeted`** ✅ | Cierra el issue #15, que hoy bloquea la feature 74 |
| 3 | **86 `tmdb_discover_quality_seeding`** ✅ | Rompe el techo de 10.000 y aplica el criterio de `vote_count` |
| 4 | **87 `openlibrary_dump_seeding`** | Elimina `search.json` del camino crítico |
| 5 | **88 `catalog_incremental_updates`** | Mantiene el catálogo sin barridos completos, incluida la promoción por umbral |

Games no necesita feature de siembra propia: su enumeración actual ya es óptima y
solo se beneficia de (1).
