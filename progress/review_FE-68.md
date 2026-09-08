# Review — FE-68 `trending_period_books_games` (+ issue #32)

**Veredicto: APPROVED**

Rama `feat/trending_period_books_games`. Revisado el working tree completo
(`git diff main` + los 4 sin trackear). Los 6 gates en verde, ejecutados por mí.

---

## 1. El arreglo del issue #32

| Comprobación | Resultado |
|---|---|
| `trendingItemType` mapea los cuatro `item_type` | ✅ `catalog-types.ts:161-164`: `toLowerCase()` + guard `isCatalogType`, contra `CATALOG_TYPES = ["movie","series","book","game"]` (`:35-40`). |
| Un valor desconocido no produce enlace roto silencioso | ✅ Devuelve `undefined`; los dos únicos llamantes descartan la tarjeta (`trending/page.tsx:90-93`, `page.tsx:70-75`). Nada de `else → series`, nada de `as CatalogType`. |
| Test que falla si alguien vuelve a colapsar el mapeo | ✅ Triple red: `catalog-types.test.ts` afirma `new Set(segments).size === 4` **y** `segments === [...CATALOG_TYPES]` (un `MOVIE ? movie : series` da `["movie","series","series","series"]`, falla por ambas); `trending/page.test.tsx` y `page.test.tsx` afirman los `href` exactos con la implementación **real** (no reimplementada en el mock: `vi.mock("@/lib/catalog")` hace spread de `@/lib/catalog-types` y solo falsea la llamada de red — el detalle que hace que estos tests muerdan de verdad). |
| Book → `/book/{slug}`, game → `/game/{slug}` | ✅ Aserción literal y negativa: `expect(hrefs).toContain("/book/un-cuento-perfecto-2020")` … `.not.toContain("/series/un-cuento-perfecto-2020")` (`trending/page.test.tsx`), con los mismos slugs del incidente real. `/book/…` y `/game/…` resuelven: la ruta `[locale]/[type]/[slug]` valida con `isCatalogType` (`page.tsx:400,433`). |
| Badge por tipo | ✅ `typeLabel: Home.typeBadge.{book,game}` existe en es/en (`Libro`/`Juego`, `Book`/`Game`). |

## 2. La copia privada de la home

✅ Eliminada (`[locale]/page.tsx:38-42` en `main` → import compartido). No queda
una tercera copia:

```
$ grep -rn "TRENDING_TYPES\|TrendingType\b" apps/web/src packages/
apps/web/src/lib/catalog-types.ts:24:  * `/trending` used to carry its own narrower `TrendingType`/`TRENDING_TYPES`
```
Única aparición: la frase del comentario que explica por qué se borraron. **Cero
referencias muertas.**

`grep -rn item_type apps/web/src` deja solo mapeos de **otras** superficies, todos
preexistentes y con su propio tipo de payload: `feedItemType`, `reviewItemType`,
`notificationItemType`, `toCatalogType` (search/library) y
`recommendations.ts:83`. Ninguno toca trending; ninguno se ha duplicado aquí.

## 3. Unificación de vocabulario — el argumento es cierto

Verificado contra el esquema generado, no contra la memoria del implementer:

```
packages/api-client/src/schema.d.ts:4508  get_trending_v1_trending_get:
:4511      type?: components["schemas"]["ItemTypeEnum"] | null;
:1943  ItemTypeEnum: "movie" | "series" | "book" | "game";
```

El query param es literalmente `ItemTypeEnum`, idéntico conjunto a `CatalogType`.
`TrendingType` era un subtipo más estrecho que el contrato: mantenerlo era
mantener la causa del #32. Borrarlo es correcto.

**Orden de las opciones del filtro:** `CATALOG_TYPES` es `movie, series, book,
game` — prefijo exacto del antiguo `TRENDING_TYPES` (`movie, series`). El select
pasa de `["", movie, series]` a `["", movie, series, book, game]`: las dos
opciones existentes **no se reordenan**, solo se añaden dos al final. Sin cambio
no intencionado. `TRENDING_PERIODS`/`DEFAULT_TRENDING_PERIOD` se conservan
correctamente (vocabulario propio de trending, no compartido con browse).

## 4. Copy

✅ Reutiliza `Search.filters` tal cual, no inventa un tercer texto:

| clave | Trending es/en | Search es/en |
|---|---|---|
| `all` | Todos los tipos / All types | idem |
| `movie`…`game` | Películas, Series, Libros, Juegos / Movies, Series, Books, Games | idem |

Paridad es/en verificada leyendo los dos JSON: las claves de `Trending.filters`
coinciden y los seis valores relevantes son iguales a los de `Search.filters` en
ambos locales.

El test **hace lo que dice**: `catalog-types.test.ts` importa los dos ficheros de
mensajes y compara `trending[k] === search[k]` para `all` + los cuatro tipos, en
`en` y `es`; más paridad de claves y el guard `all` sin la palabra «series» (que
mordería tanto el viejo «Películas y series» como «Movies & series»). Sin
strings hardcodeados en el componente: `trending-filters.test.tsx` comprueba que
las cinco `<option>` se etiquetan con su clave i18n.

## 5. `parseType`

✅ `trending/page.tsx:21-30`: valida con `isCatalogType`, acepta los cuatro y
degrada a «sin filtro» ante basura — nunca reenvía un valor inválido al backend
(que respondería 422). Cubierto: `?type=movie|series|book|game` → forwarded;
`?type=podcast` → `{ type: undefined }`; `?period=century` → default `week`.

## 6. `packages/api-client` regenerado

✅ El diff son **exactamente** los 3 cambios esperados y ninguno más
(`openapi.json` +7/−2, `schema.d.ts` +6/−1):

1. descripción de `GET /v1/trending` (la corrigió la feature 81 en
   `backlogg/trending/router.py:16`),
2. descripción del tag `trending` (`backlogg/main.py:108`),
3. campo aditivo `skipped_links` en `SyncResponse` (`type: integer`,
   `default: 0`).

**Coherencia openapi.json ↔ schema.d.ts: verificada empíricamente.** Re-ejecuté
`pnpm --filter @backlogg/api-client gen:api` y los dos ficheros salen
**byte-idénticos** a los del working tree (`diff -q` sin salida en ambos), o sea
que `schema.d.ts` corresponde a este `openapi.json` y este `openapi.json`
corresponde al backend de la rama. `typecheck` en verde.

**`skipped_links: number` (no opcional): no rompe nada.** Es respuesta, no
request — `apps/web` nunca construye un `SyncResponse`. `grep -rn
"skipped_links\|people_errors" apps/web/src` → **cero resultados**: ni siquiera se
lee. Además el vecino `people_errors` ya estaba emitido igual por la misma razón
(`default`), así que no es un patrón nuevo. `pnpm --filter web typecheck` y
`build` en verde lo confirman.

## 7. Alcance

✅ `git status --short` toca solo `apps/web/**`, `packages/api-client/**`,
`progress/**` y los dos JSON de backlog (`frontend_feature_list.json`: un
`pending → in_progress`; `issues_list.json`: alta del #32 — ambos tuyos).
**Nada** en `backlogg/`, `tests/`, `alembic/` ni `bruno/`. `bruno/Trending/` ya
tenía `type book` y `type game` desde el backend: no hay endpoint nuevo ni
cambio de contrato que sincronizar.

---

## 8. El criterio de aceptación contra el backend real — reproducido

Levanté el backend yo mismo (`uv run uvicorn backlogg.main:app --port 8011`, DB
de dev en `backlogg-db`), consulté las ocho combinaciones y **lo apagué**.
Reproduzco los números del implementer **exactamente**:

```
movie   day n=20 week n=20 identical_list=False only_in_week=10 only_in_day=10
series  day n=20 week n=20 identical_list=False only_in_week=7  only_in_day=7
book    day n=20 week n=20 identical_list=True  only_in_week=0  only_in_day=0
game    day n= 5 week n=16 identical_list=False only_in_week=11 only_in_day=0
no type: Counter({'MOVIE': 5, 'SERIES': 5, 'BOOK': 5, 'GAME': 5}) total 20
```

Y verifiqué la causa que alega, contra la DB, no contra su palabra:

```
$ docker exec backlogg-db psql -U postgres -d backlogg -c "select count(*) total,
    count(*) filter (where first_publish_date > current_date - interval '365 days') within_365,
    count(*) filter (where first_publish_date > current_date - interval '90 days') within_90,
    max(first_publish_date) from books;"
 total | within_365 | within_90 |  max_date
-------+------------+-----------+------------
   391 |          0 |         0 | 2025-01-01
```

**Dictamen: limitación legítima del dato de dev. No es motivo de rechazo.**

Razonamiento, no indulgencia:

1. La ventana de estreno del fallback es 90 d (`day`) y 365 d (`week`)
   (`docs/api.md:1078`). Hoy es 2026-09-08 y el libro más reciente del catálogo
   es de 2025-01-01: **616 días**. Las dos ventanas devuelven cero.
2. `docs/api.md:1061-1065` especifica que con resultado **totalmente** vacío la
   ventana se relaja al catálogo completo. Con cero en ambas, los dos periodos
   colapsan al mismo orden canónico. El resultado observado es exactamente el
   comportamiento **especificado**, y el propio doc anticipa este caso por
   nombre: «el caso normal en libros, cuya fecha es la de publicación original».
   Es decir: no es un efecto colateral no previsto, es la rama documentada.
3. La causa está **aguas arriba del frontend**. `period` sale del front igual
   para los cuatro tipos: sin ramas por tipo en `parsePeriod`/`getTrendingPage`,
   y hay test de la query real emitida (`?type=game&period=day`) más el
   forwarding de los cuatro tipos. No hay nada que FE-68 pudiera hacer distinto
   que cambiara ese resultado.
4. `game` — el otro tipo nuevo, mismo código, misma ruta — **sí** diverge de
   forma inequívoca (5 vs 16, 11 exclusivos de `week`). Eso acredita de punta a
   punta que `period` es real para los tipos que la feature añade; `book` recorre
   ese mismo camino y solo se queda sin dato que lo diferencie.

Lo que el criterio pretendía verificar era que `period` dejase de ser **inerte**
para book/game (la limitación de la feature backend 68). Está verificado: hoy
`period` entra en el `WHERE` también para book — lo que no hay es catálogo dentro
de esas ventanas. Rechazar aquí sería exigir que el frontend cambie la fecha de
publicación de 391 libros. Lo correcto es lo que hizo el implementer: reportarlo
medido y explicado, no maquillarlo.

⚠️ **Para la QA del leader**: la única parte del criterio no observable hoy
(`book` con `day ≠ week`) quedará observable en cuanto el catálogo tenga libros
recientes o `≥ TRENDING_MIN_ACTIVITY` gestos en la ventana. No requiere tocar el
frontend.

---

## Checkpoints (`CHECKPOINTS.md`)

Feature 100 % frontend: no hay modelos, migraciones, endpoints, fechas de APIs
externas, fallback on-demand, scheduler ni capas Python en el diff.

- **C1** `bash init.sh` exit 0 — [x]
- **C2** sin `print()`/debug en el código nuevo — [x] (los `console.error` de
  `catalog.ts` son el logging de error preexistente del módulo, no nuevos)
- **C3** sin TODOs sin contexto — [x] (`grep TODO/FIXME/XXX` limpio)
- **C4** `ruff check` + `ruff format --check` — [x] (vía init.sh)
- **C5** `uv run pytest` — [x] 1499 passed
- **C6, C7, C8** modelos/migraciones — N/A
- **C9–C13** endpoints — N/A
- **C14, C15** fechas y datos externos — N/A
- **C16, C17** fallback on-demand — N/A
- **C18, C19** scheduler — N/A
- **C20, C21, C22** capas Python — N/A

Equivalente frontend (`frontend_feature_list.json`, acceptance de FE-68):

- period efectivo en los cuatro tipos — [x] (backend 81 + front lo envía sin ramas)
- verificado contra backend real que `day` ≠ `week` — [x] game / ⚠️ book (§8)
- sin strings hardcodeados, claves next-intl en es.json y en.json — [x]
- typecheck && lint && build && test en verde — [x]

---

## Observaciones que NO bloquean

1. `apps/web/src/lib/recommendations.ts:83` hace
   `item.item_type.toLowerCase() as CatalogType` — cast ciego, sin guard, el
   mismo patrón que causó el #32 pero en otra superficie. Preexistente y fuera
   de alcance; candidato a issue propio.
2. Hay **cinco** funciones `*ItemType` casi idénticas (trending, feed, review,
   notification, search/`toCatalogType`). Todas correctas; la duplicación es
   preexistente y consciente (cada una tipa su payload). No es deuda urgente,
   pero es donde volvería a nacer un #32.
3. Si `getTrending()` devolviese solo tipos desconocidos, la home renderizaría
   una rejilla vacía en vez del mensaje `trendingEmpty` (`page.tsx`: el
   `!type → null` va dentro del `map`, después del check de `length`). Caso
   irreal hoy (implicaría un quinto tipo backend). Cosmético.
4. El implementer verificó que sus tests muerden revirtiendo el mapeo
   temporalmente (12 fallos). No lo repliqué por no escribir en su código, pero
   las aserciones son deterministas por lectura: `new Set(segments).size === 4`
   y los `href` literales fallan por construcción con un mapeo binario.
5. El `build` emite `DYNAMIC_SERVER_USAGE` en `/admin/*`, `/settings` y
   `/recommendations` durante el prerender. Exit code 0; rutas que leen
   `cookies`, ajenas a este diff. Preexistente.

---

## Output de los comandos

```
### pnpm --filter web typecheck
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
EXIT=0

### pnpm --filter web lint
$ eslint
EXIT=0

### pnpm --filter @backlogg/api-client typecheck
$ tsc --noEmit
EXIT=0

### pnpm --filter web test
 Test Files  133 passed (133)
      Tests  1229 passed (1229)
   Start at  08:30:23
   Duration  38.65s (transform 8.85s, setup 91.25s, import 38.54s, tests 77.11s, environment 158.55s)

### pnpm --filter web build
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully
✓ Generating static pages (69/69)
ƒ Proxy (Middleware)
○  (Static)   prerendered as static content
●  (SSG)      prerendered as static HTML (uses generateStaticParams)
ƒ  (Dynamic)  server-rendered on demand
BUILD_EXIT=0

### pnpm --filter @backlogg/api-client gen:api  (comprobación de coherencia del reviewer)
GEN_EXIT=0
diff openapi.before.json  packages/api-client/openapi.json   → openapi identical
diff schema.before.d.ts   packages/api-client/src/schema.d.ts → schema identical

### bash init.sh
........................................................................ [  9%]
... (20 líneas de puntos) ...
...........................................................              [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x...> with identity key
  (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None)
  conflicts with persistent instance <Credit at 0x...>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1499 passed, 1 warning in 35.90s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
INIT_EXIT=0
```
