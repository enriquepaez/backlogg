# Implementación FE-68 `trending_period_books_games` (+ issue #32)

Rama: `feat/trending_period_books_games`. Fecha: 2026-09-08. Alcance tocado:
solo `apps/web`.

## Archivos

**Modificados**

- `apps/web/src/lib/catalog-types.ts` — se elimina el vocabulario paralelo
  `TrendingType`/`TRENDING_TYPES` y se añade `trendingItemType()`.
- `apps/web/src/lib/catalog.ts` — se borra el `trendingItemType()` binario;
  `TrendingPageOptions.type` pasa a `CatalogType`.
- `apps/web/src/components/trending-filters.tsx` — el selector recorre
  `CATALOG_TYPES`.
- `apps/web/src/app/[locale]/trending/page.tsx` — `parseType` valida con
  `isCatalogType`; se salta la tarjeta sin ruta conocida.
- `apps/web/src/app/[locale]/page.tsx` — la home deja de tener su copia
  privada del mapeo y usa la compartida.
- `apps/web/messages/es.json`, `apps/web/messages/en.json` — copy de
  `Trending.filters`.
- `apps/web/src/test/msw/handlers.ts` — `trendingFixture` pasa a mezclar los
  cuatro tipos y el handler filtra por cualquiera de ellos.
- `apps/web/src/lib/catalog.test.ts`,
  `apps/web/src/components/trending-filters.test.tsx` — tests actualizados.

**Creados**

- `apps/web/src/lib/catalog-types.test.ts`
- `apps/web/src/app/[locale]/trending/page.test.tsx`
- `apps/web/src/app/[locale]/page.test.tsx`

## Qué se implementó y por qué

### 1. Un solo vocabulario de tipos, no dos

`TrendingType`/`TRENDING_TYPES` (`"movie" | "series"`) **se han eliminado**.
Todo el trending usa ya `CatalogType`/`CATALOG_TYPES`.

No es una decisión estética: en el esquema generado, el query param `type` de
`GET /v1/trending` es literalmente `ItemTypeEnum`
(`"movie" | "series" | "book" | "game"`,
`packages/api-client/src/schema.d.ts:4506` → `:1943`), el mismo conjunto que
`CatalogType`. Eran dos nombres para el mismo conjunto, y mantener el segundo
solo sirve para que vuelvan a divergir — que es exactamente lo que fue el issue
#32. Un alias (`type TrendingType = CatalogType`) habría dejado la puerta
abierta a volver a estrecharlo en un sitio y no en el otro; borrarlo hace
imposible que las dos listas discrepen. El *rationale* queda escrito en el
comentario de `CatalogType`.

`TRENDING_PERIODS` y `DEFAULT_TRENDING_PERIOD` se quedan: `period` sí es
vocabulario propio de trending (`day`/`week`), no compartido con browse.

### 2. `trendingItemType()` mapea los cuatro y no adivina

Se movió de `catalog.ts` a `catalog-types.ts` (módulo sin `server-only`, ni
directo ni transitivo). Dos motivos:

- Es vocabulario puro, sin red — es donde el propio doc del módulo dice que
  debe vivir. `catalog.ts` sigue re-exportándolo (`export * from
  "./catalog-types"`), así que los imports existentes desde `@/lib/catalog` no
  cambian.
- Permite que los tests de página usen **la implementación real** en vez de
  una reimplementada en el mock (ver más abajo). Si el mapeo se reduce a dos
  tipos, los tests de `/trending` y de la home fallan de verdad.

Implementación:

```
export function trendingItemType(item: { item_type: string }): CatalogType | undefined
```

minúscula + guard `isCatalogType`. Es el **mismo idiom que ya usaban**
`feedItemType` (`feed-entry-list.tsx`) y `toCatalogType` (`@/lib/search.ts`)
para esta misma forma del backend: reutilizado en vez de inventar un tercer
patrón (p. ej. un `Record` exhaustivo).

Firma estructural `{ item_type: string }` en lugar de `TrendingItem` para que
`catalog-types.ts` conserve sus cero imports; todo `TrendingItem` la satisface.

**Qué pasa con un valor desconocido: se devuelve `undefined` y el llamante
descarta la tarjeta.** Justificación: el daño del issue #32 no fue el 404, fue
el enlace *silenciosamente correcto-en-apariencia* — `/series/un-cuento-perfecto-2020`
aterrizaba en una serie real distinta y además disparaba ingesta on-demand.
Frente a eso, una tarjeta ausente es un hueco recuperable y visible; un enlace
confiadamente equivocado no. No se usó un `else` a `series` ni un fallback a
`movie` por lo mismo. Se descartó también lanzar: es una sección pública de
SEO donde una fila rara no debe tumbar la página (misma filosofía de
degradación que el resto de `catalog.ts`).

La home tenía su **propia copia** del mapeo (`[locale]/page.tsx:39`), con el
mismo bug: `getTrending()` sin `type` devuelve los cuatro tipos, así que la
sección de tendencias de la portada enlazaba mal exactamente igual. Copia
eliminada; ahora importa la compartida. Entra en el arreglo porque es el mismo
defecto, no otra feature.

### 3. Copy

`Trending.filters` en es/en:

| clave | es | en |
|---|---|---|
| `all` | `Todos los tipos` | `All types` |
| `movie` | `Películas` | `Movies` |
| `series` | `Series` | `Series` |
| `book` | `Libros` (nueva) | `Books` (nueva) |
| `game` | `Juegos` (nueva) | `Games` (nueva) |

La opción «todo» ya no dice «Películas y series» / «Movies & series».

Sobre el texto elegido: la indicación era «algo tipo Todo/All», pero al mirar
otras superficies aparece que **`Search.filters` es exactamente el mismo
control** (`typeLabel` + `all` + los cuatro tipos) y ya dice
«Todos los tipos»/«All types», con los tipos nombrados igual que
`Home.types` y `Browse.heading` (`Libros`/`Juegos`). Se reutiliza ese
vocabulario tal cual en vez de introducir un tercer texto para el mismo
concepto; hay un test que exige que `Trending.filters` y `Search.filters`
coincidan literalmente en esas seis claves.

### 4. `parseType`

Sigue validando contra el vocabulario, ahora vía `isCatalogType`, así que
acepta los cuatro. Un `?type=` fuera de vocabulario sigue degradando a
«sin filtro» (nunca se reenvía al backend, que respondería 422).

## Tests

- `catalog-types.test.ts` — los cuatro `item_type` a su segmento; que los
  cuatro segmentos sean distintos (un mapeo colapsado se delata aquí);
  `undefined` para `PODCAST`/`""`; paridad es/en de `Trending.filters`;
  existencia de copy para cada tipo de `CATALOG_TYPES`; igualdad con
  `Search.filters`; y que `all` ya no mencione «series».
- `trending/page.test.tsx` (nuevo) — **test de regresión del issue #32**: una
  tarjeta de book enlaza a `/book/{slug}` y una de game a `/game/{slug}`, y
  explícitamente **no** a `/series/{slug}`; badges por tipo; item de tipo
  desconocido descartado; `?type=movie|series|book|game` parseado y
  **pasado al cliente de API** (`getTrendingPage({ type, period })`);
  `?type=` inválido → sin filtro; `?period=` inválido → default.
- `[locale]/page.test.tsx` (nuevo) — lo mismo para la sección de tendencias de
  la home, para que no vuelva a aparecer una copia privada del mapeo.
- `trending-filters.test.tsx` — el select ofrece `["", movie, series, book,
  game]`, cada opción se etiqueta con su clave i18n, y book/game navegan como
  cualquier otro tipo.
- `catalog.test.ts` — `trendingFixture` ya mezcla los cuatro tipos (antes solo
  movie+series: era la propia suposición del bug); `getTrendingPage({type:
  "book"|"game"})` filtra; y un test que comprueba la query real emitida:
  `?type=game&period=day`.

**Comprobación de que los tests muerden**: se revirtió temporalmente
`trendingItemType` a `item_type === "MOVIE" ? "movie" : "series"` y fallaron
12 tests en los 3 archivos (5 de vocabulario, 4 de `/trending`, 3 de la home).
Revertido de vuelta.

## Verificación contra el backend real (criterio de aceptación de FE-68)

Backend levantado en local (`uv run uvicorn backlogg.main:app --port 8000`,
DB de dev en el contenedor `backlogg-db`), consultado y **apagado al
terminar**. Comparando las listas de slugs de `day` vs `week`:

```
movie   day n=20  week n=20  identical_list=False  only_in_week=10  only_in_day=10
series  day n=20  week n=20  identical_list=False  only_in_week=7   only_in_day=7
book    day n=20  week n=20  identical_list=True   only_in_week=0   only_in_day=0
game    day n= 5  week n=16  identical_list=False  only_in_week=11  only_in_day=0
no type filter: Counter({'MOVIE': 5, 'SERIES': 5, 'BOOK': 5, 'GAME': 5}) total 20
```

Muestra de `type=game`:

```
=== type=game period=day        (5)
   grand-vegas-casino 2026-06-17
   final-fantasy-xiv-evercold 2027-01-01
   deadly-obsession 2026-06-26
   the-prince-of-tennis-...-tie-break-game 2026-07-30
   grand-theft-auto-vi-ultimate-edition 2026-11-19
=== type=game period=week       (16)
   lego-batman-legacy-of-the-dark-knight 2026-05-22
   escape-from-tarkov 2025-11-15
   meow-dream-home 2025-11-04
   grand-vegas-casino 2026-06-17
   ... (+12)
```

**Resultado honesto: `game` sí, `book` no — y el motivo no es el frontend.**

- `game`: `day` y `week` devuelven listas claramente distintas (5 vs 16 items,
  11 exclusivos de `week`). El `period` llega al backend y tiene efecto real.
  Esto acredita el criterio de aceptación de punta a punta para uno de los dos
  tipos nuevos.
- `book`: `day` y `week` devuelven **exactamente la misma lista**. Comprobado
  el porqué contra la DB:

  ```
  select count(*) filter (where first_publish_date > current_date - interval '365 days'),
         count(*) filter (where first_publish_date > current_date - interval '90 days'),
         max(first_publish_date) from books;
  →  0 | 0 | 2025-01-01
  ```

  No hay ni un libro con fecha de publicación dentro de la ventana de `week`
  (365 d) ni de `day` (90 d). Según `docs/api.md`, cuando la ventana del
  fallback deja **cero** resultados se relaja y se sirve el orden canónico
  sobre todo el catálogo: eso ocurre para los dos periodos, así que ambos
  colapsan al mismo orden. Es el comportamiento documentado del backend, con
  la DB de dev sin actividad local ni estrenos de libros recientes — no un
  fallo del frontend ni de la feature 81. Con actividad real (`≥
  TRENDING_MIN_ACTIVITY` gestos en la ventana) o con libros publicados
  recientemente en catálogo, `book` entraría por la señal local/ventana y las
  listas divergirían como en `game`.

  Lo que sí queda verificado en el frontend es que `period` **se envía** para
  book igual que para el resto (test de la query emitida en `catalog.test.ts`
  y forwarding en `trending/page.test.tsx`).

## Hallazgos fuera de alcance (no tocados)

1. `apps/web/src/lib/catalog.ts` conserva comentarios que dicen que trending es
   «TMDB-backed» y que «un hit sin caché llama a TMDB y escribe items nuevos»
   (doc de módulo y de `TRENDING_REVALIDATE_SECONDS`). Desde la feature backend
   81 eso ya no es cierto (`docs/api.md`: «no hay ninguna llamada externa»). No
   se han tocado por no ampliar el diff; son comentarios, no comportamiento.
2. `packages/api-client/src/schema.d.ts:725` sigue describiendo `/v1/trending`
   como «period is accepted but has no effect for those two types». Es la
   descripción del OpenAPI del backend regenerada; corregirla es del backend,
   y `packages/api-client/` está fuera de alcance.
3. No se ha tocado `bruno/`: no hay endpoints nuevos ni cambios de contrato.

## Verificación obligatoria

```
### pnpm --filter web typecheck
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully

### pnpm --filter web lint
$ eslint
(exit=0)

### pnpm --filter web test
 RUN  v4.1.10 /home/enriquepaez/projects/backlogg/apps/web

 Test Files  133 passed (133)
      Tests  1229 passed (1229)
   Start at  08:22:32
   Duration  27.36s (transform 6.55s, setup 66.80s, import 26.45s, tests 52.15s, environment 112.05s)

### pnpm --filter web build
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully in 213ms
  Finished TypeScript in 2.1s ...
○ (serwist) Using esbuild-wasm to bundle the service worker.
✓ Generating static pages using 11 workers (69/69) in 1440ms
  Finalizing page optimization ...
ƒ Proxy (Middleware)
○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```

Los cuatro en verde (`build` sale con exit 0; los `DYNAMIC_SERVER_USAGE` de
`/admin/*`, `/settings` y `/recommendations` durante el prerender son
preexistentes y no relacionados con este cambio: son rutas que leen `cookies`).

## Nota

No he marcado `done` la feature ni he tocado `issues_list.json`, `docs/` ni
`progress/current.md`. Estado en `frontend_feature_list.json`: `in_progress`.

---

## Remate 1 — comentarios obsoletos de trending (misma rama)

Solo comentarios/docstrings; **cero cambios de comportamiento** (el diff de
código ejecutable es vacío en estos dos archivos respecto al estado anterior
del remate).

| Dónde | Decía | Dice ahora |
|---|---|---|
| `catalog.ts`, doc de módulo | «the home page's trending (**TMDB-backed**)» | sin el paréntesis: trending es local como el resto |
| `catalog.ts`, `TRENDING_REVALIDATE_SECONDS` | «**TMDB trending** shifts through the day, and an uncached hit both **calls TMDB and writes newly-seen items** to the local DB» | la ventana es corta porque el ranking se calcula sobre actividad reciente con decaimiento exponencial (feature 81); **no hay llamada externa** — el descubrimiento pasó a la siembra + sync nocturno; se menciona el caché del backend por `(type, period)` (`CACHE_TTL_TRENDING`) |
| `catalog.ts`, `getTrending()` | «Trending movies + series (this week), **TMDB-backed**.» | mezcla de **los cuatro** tipos (~5 de cada uno, tope 20), `period` default `week`, ranking local; y aviso de mapear con `trendingItemType` (issue #32) |
| `catalog.ts`, `getTrendingPage()` | (sin mención) | añadido: `type` acepta los cuatro (feature 68) y `period` es real para todos (feature 81), la vieja salvedad «period inerte para book/game» ya no aplica |
| `catalog-types.ts`, doc de `CatalogType` | «from back when trending **was TMDB-backed**» | reformulado como historia explícita: el endpoint *proxyaba* la Trending API de TMDB (de ahí los dos tipos) y las features 68/81 **eliminaron esa fuente** |
| `catalog-types.ts`, `trendingItemType()` | «trigger on-demand ingestion» (ambiguo: parecía atribuirlo a `/trending`) | aclarado: la ingesta on-demand la dispara **la ruta de detalle**, no trending |

Las dos únicas menciones a TMDB que quedan en el código de trending están
redactadas explícitamente en pasado («used to proxy», «from back when»). La
tercera aparición del fichero (`getSimilarItems`, línea ~483) es de `/similar`,
sigue siendo cierta y no se ha tocado.

## Remate 2 — regeneración de `packages/api-client`

`pnpm --filter @backlogg/api-client gen:api` (introspección de
`backlogg.main:app`, sin DB). Diff **exactamente los 3 cambios medidos por el
leader, ninguno más**:

1. `openapi.json` + `schema.d.ts` — descripción del endpoint
   `GET /v1/trending`: fuera la frase falsa («Movies/series come from TMDB's
   Trending API… period is accepted but **has no effect** for those two
   types»), dentro la real (actividad local con decaimiento, sin API externa,
   fallback al orden canónico, «period … has a real effect for all four
   types»).
2. `openapi.json` — descripción del **tag** `trending`: «Trending movies and
   series from the TMDB Trending API» → «ranked from the platform's own recent
   activity, with a catalog fallback when activity is too thin».
3. `openapi.json` + `schema.d.ts` — campo **aditivo** `skipped_links` en
   `SyncResponse` (issue #22), `type: integer`, `default: 0`.

Total: `openapi.json` 9 líneas (+7/-2), `schema.d.ts` 7 líneas (+6/-1). **No
hay ningún tipo que cambie de forma ni ningún campo requerido nuevo.**

Matiz sobre el punto 3, por si el reviewer lo mira: `skipped_links` **no** está
en el `required` del schema, pero `openapi-typescript` lo emite sin `?`
(`skipped_links: number;`) por tener `default` — es su comportamiento normal
para respuestas, idéntico al del vecino `people_errors`, que ya estaba así. No
rompe a nadie: `apps/web` no referencia `skipped_links` ni `people_errors` en
ningún sitio (grep sin resultados), así que no hay literales de `SyncResponse`
que construir en el frontend.

### Gates tras regenerar (los cuatro de `apps/web` + el del cliente)

```
### pnpm --filter @backlogg/api-client typecheck
$ tsc --noEmit
(exit=0)

### pnpm --filter web typecheck
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully

### pnpm --filter web lint
$ eslint
(exit=0)

### pnpm --filter web test
 Test Files  133 passed (133)
      Tests  1229 passed (1229)
   Duration  32.44s

### pnpm --filter web build
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully in 500ms
  Finished TypeScript in 5.2s ...
✓ Generating static pages using 11 workers (69/69) in 1472ms
  Finalizing page optimization ...
(build exit=0)
```

Los cinco en verde. `packages/api-client/openapi.json` y
`packages/api-client/src/schema.d.ts` quedan modificados en el working tree,
sin commitear.
