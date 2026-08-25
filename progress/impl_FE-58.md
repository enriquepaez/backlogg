# FE-58 — game_type_display_labels

## Archivos creados

- `apps/web/src/lib/game-type-labels.ts` — mapa de códigos IGDB
  (`GAME_TYPE_CODES`) y `gameTypeLabel(value, t)` (traduce con fallback),
  usado por `page.tsx` (sección 2). Ya no incluye `gameTypeBadgeLabel` —
  ver sección 3 (revertido tras review).
- `apps/web/src/lib/game-type-labels.test.ts` — tests unitarios del helper.

## Archivos modificados

- `apps/web/messages/en.json`, `apps/web/messages/es.json` — nuevo namespace
  `ItemDetail.gameTypes` con las 15 categorías + `other` (fallback).
- `apps/web/src/app/[locale]/[type]/[slug]/page.tsx` — el campo `gameType`
  de `buildFields` usa `gameTypeLabel(game.game_type, t)` en vez del valor
  crudo; se preserva el placeholder "Not available" para el caso
  (defensivo) de `game_type` ausente.
- `apps/web/src/app/[locale]/[type]/[slug]/page.test.tsx` — fixture
  `gameItem.game_type` corregido a `"MAIN_GAME"` (antes `"main_game"`,
  minúsculas, que nunca es un valor real del backend); nuevo describe con
  un test parametrizado para las 15 categorías + fallback + placeholder.
- `apps/web/src/components/catalog-card.tsx` — sin cambios netos tras la
  revisión (ver sección 3): se añadió y luego se revirtió un prop
  `gameTypeLabel?: string` sin caller real.
- `apps/web/src/components/catalog-card.test.tsx` — sin cambios netos tras
  la revisión (ver sección 3).

## Resumen y decisiones

### 1. Mapa de traducción — 15 categorías, no 14

La descripción de la feature (y `progress/current.md`) dice "14 categorías
IGDB". Verifiqué la fuente de verdad citada,
`backlogg/games/constants.py::GAME_TYPE_MAP`, y tiene **15** entradas
(índices 0-14): `MAIN_GAME, DLC_ADDON, EXPANSION, BUNDLE,
STANDALONE_EXPANSION, MOD, EPISODE, SEASON, REMAKE, REMASTER,
EXPANDED_GAME, PORT, FORK, PACK, UPDATE`. Implementé las 15 (el conteo de
"14" en el ticket es un desliz de un dígito) porque la fuente de verdad
explícita es el código del backend, no la descripción de la tarea, y
omitir una categoría real habría dejado exactamente el bug original (valor
crudo sin traducir) para esa categoría.

Etiquetas elegidas (EN / ES), términos reconocibles para jugadores:

| Código | EN | ES |
|---|---|---|
| MAIN_GAME | Main Game | Juego principal |
| DLC_ADDON | DLC | DLC |
| EXPANSION | Expansion | Expansión |
| BUNDLE | Bundle | Paquete |
| STANDALONE_EXPANSION | Standalone Expansion | Expansión independiente |
| MOD | Mod | Mod |
| EPISODE | Episode | Episodio |
| SEASON | Season | Temporada |
| REMAKE | Remake | Remake |
| REMASTER | Remaster | Remasterización |
| EXPANDED_GAME | Expanded Edition | Edición ampliada |
| PORT | Port | Adaptación |
| FORK | Fork | Versión derivada |
| PACK | Content Pack | Paquete de contenido |
| UPDATE | Update | Actualización |
| (fallback) | Other | Otro |

`BUNDLE` y `PACK` son conceptualmente parecidos (un lote de contenido) pero
se etiquetan distinto en ambos idiomas para no perder la distinción que
IGDB sí hace entre ambos.

### 2. Detail page

`buildFields`'s `game` branch ya no usa `orNotAvailable(game.game_type, t)`
a secas: `game_type` es un campo requerido no-nulo en `GameOut`
(`schema.d.ts`), así que a diferencia de los demás campos de ese switch,
un valor *presente* también necesita traducción antes de mostrarse — no
basta con el placeholder para el caso nulo. Nueva lógica:
`game.game_type != null ? gameTypeLabel(game.game_type, t) : t("fields.notAvailable")`,
preservando el placeholder para el caso (defensivo) de valor ausente.

### 3. CatalogCard — decisión sobre `game_type` en las grids

Antes de tocar `CatalogCard` verifiqué qué respuestas de la API realmente
traen `game_type` (`packages/api-client/src/schema.d.ts`):

- `GameListItemOut` (browse/home/trending) — **no** lo trae.
- `SimilarMovieOut` (usado también para "similar" de juegos) — **no** lo trae.
- `LibraryItemOut` (biblioteca) — **no** lo trae.
- `SearchResultItem` (búsqueda) — **no** lo trae.
- `GameOut` (detail, un solo item) — es la **única** respuesta que lo trae.

Es decir: hoy ningún caller que arma props de `CatalogCard` para juegos
tiene el dato `game_type` disponible en absoluto — no es una omisión de
implementación de este ticket, es que el propio backend no expone ese
campo en ningún endpoint de lista/grid.

**Actualización post-review (CHANGES_REQUESTED):** la primera vuelta de
esta feature añadió, de todos modos, un prop `gameTypeLabel?: string` a
`CatalogCard` y una función `gameTypeBadgeLabel` en
`lib/game-type-labels.ts` (con la política "omitir `MAIN_GAME`"),
anticipando el día en que algún schema de lista exponga `game_type`. El
reviewer verificó con grep que **ningún caller real** en `apps/web/src`
pasaba ese prop y lo marcó como código muerto/especulativo — abstracción
para un caso de uso que no existe todavía, lo cual viola la convención del
proyecto de no diseñar para hipotéticos. Se revirtió ambas piezas:

- `CatalogCard` ya **no** tiene prop `gameTypeLabel` ni renderiza ningún
  badge de tipo de juego; queda exactamente como estaba antes de esta
  feature (solo con el badge de `itemType`/`typeLabel` de FE-57 y el de
  `libraryStatus`, sin tocar).
- `lib/game-type-labels.ts` ya **no** tiene `gameTypeBadgeLabel`; conserva
  únicamente `gameTypeLabel`/`GAME_TYPE_CODES`, que sí tienen caller real
  en `page.tsx` (ver sección 2).

Esa parte del acceptance de la feature ("CatalogCard muestra el
`game_type` traducido en las grids donde aplica") queda **no aplicable
hoy**: ningún schema de lista/grid expone `game_type` desde el backend,
solo el detail (`GameOut`), y ese caso ya está cubierto por el cambio en
`page.tsx` (sección 2). Se implementará en `CatalogCard` cuando exista una
feature de backend que añada el campo a algún schema de lista — en ese
momento se reintroducirá el prop y la política de omisión de `MAIN_GAME`
junto con su(s) caller(s) real(es), en vez de dejar plumbing sin
consumidor por adelantado.

### 4. Fallback para valor no reconocido

`gameTypeLabel` usa `ItemDetail.gameTypes.other`
("Other"/"Otro") para cualquier string fuera de las 15 conocidas — cubre
una categoría IGDB futura sin crashear ni mostrar texto vacío/crudo.
Cubierto por tests explícitos en `game-type-labels.test.ts` y en
`page.test.tsx`.

## Verificación — `apps/web` (pnpm)

Re-ejecutado íntegro tras aplicar los cambios pedidos por el reviewer
(revertir `gameTypeLabel`/`gameTypeBadgeLabel` sin caller real, sección 3).

### `pnpm typecheck`
```
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
```

### `pnpm lint`
```
$ eslint
```
(sin salida = sin errores/warnings)

### `pnpm test`
```
 Test Files  128 passed (128)
      Tests  1159 passed (1159)
```
(1159 = 1178 - 19: los 3 tests de `CatalogCard`/`gameTypeLabel` prop y los
16 de `gameTypeBadgeLabel` — 1 MAIN_GAME + 14 no-MAIN_GAME parametrizados +
1 fallback — eliminados junto con el código muerto que cubrían.)

### `pnpm build`
Exit code 0. Salida de rutas generada sin errores.

## Fuera de alcance (documentado, no implementado)

- Añadir `game_type` a `GameListItemOut`/`SimilarMovieOut`/`LibraryItemOut`/
  `SearchResultItem` en el backend, que es lo único que permitiría a un
  caller real de `CatalogCard` pasar `gameTypeLabel` en una grid. Sería una
  feature de backend aparte.
