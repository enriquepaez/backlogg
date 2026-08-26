# Detail page layout — orden de los campos de metadata

> Decidido con el usuario el 2026-08-26, pendiente de implementación en
> `apps/web/src/app/[locale]/[type]/[slug]/page.tsx` (`buildFields`, feature
> frontend futura). Este documento es la fuente de verdad del *orden*; el
> código es la fuente de verdad una vez implementado — si divergen,
> actualiza este archivo.

## Contexto

Las 4 detail pages (movie/series/book/game) comparten un bloque de "campos
de metadata" (`buildFields` en `page.tsx`) con un orden hoy distinto en
cada tipo, sin ningún criterio explícito. Además hay campos que la API de
origen de ese tipo nunca puede rellenar (no es un bug de sync, es que el
dato no existe en esa fuente) — hay que distinguir "el campo no tiene valor
para este item" de "este tipo de contenido nunca va a tener valor aquí".

## Principio de orden

Dentro del bloque de metadata, los campos van en 3 grupos, siempre en este
orden:

1. **Comunes** (existen en el schema de los 4 tipos) — misma posición
   siempre, aunque el dato no exista para ese tipo concreto.
2. **Parciales** (existen en más de un tipo pero no en los 4) — misma
   posición siempre que el campo exista para ese tipo; si el tipo no lo
   tiene, esa fila simplemente no aparece (no se deja hueco vacío).
3. **Específicos** (solo existen en un tipo) — van al final, en el orden
   que tenga sentido para ese tipo.

`rating_external`/`rating_internal`, `genres` y `viewer_status` no forman
parte de este bloque — ya tienen posición fija propia fuera de él (badge de
rating, pills de género, botones "Your status") y no cambian con esta
decisión.

## Grupo 1 — Comunes (posición 1-2 en los 4 tipos)

| Orden | Campo | Movie | Series | Book | Game |
|---|---|---|---|---|---|
| 1 | Fecha principal (`release_date`/`first_air_date`/`first_publish_date`) | ✅ | ✅ | ✅ | ✅ |
| 2 | `original_language` | ✅ dato real (TMDB) | ✅ dato real (TMDB) | ⚠️ nunca rellenable | ⚠️ nunca rellenable |

**`original_language` en book/game — limitación de la fuente, no un bug**:
Open Library modela los libros a nivel de *work* (`docs/schema.md`), y el
idioma es un dato de *edition*, no de work — no existe un campo de idioma
fiable al nivel que se sincroniza. IGDB no modela "idioma original" como
concepto en absoluto (los juegos se localizan a muchos idiomas sin uno
"original" canónico como una película o un libro). Confirmado en código:
`backlogg/books/adapters/open_library.py:383` e
`backlogg/games/adapters/igdb.py:258` fijan `"original_language": None` a
propósito — no falta sincronizar nada, la fuente no lo tiene.

**Decisión pendiente**: ¿se mantiene el campo visible con placeholder "Not
available" en book/game (comportamiento actual, feature frontend FE-63), o
se oculta directamente el campo para esos 2 tipos ya que se sabe que nunca
va a tener valor? No decidido todavía — el usuario lo revisará más
adelante.

## Grupo 2 — Parciales (posición 3, solo donde exista)

| Orden | Campo | Movie | Series | Book | Game |
|---|---|---|---|---|---|
| 3 | `status` (release/production status — RELEASED/RETURNING/...) | ✅ | ✅ | ❌ no existe | ❌ no existe |

Nota: este `status` es un concepto de catálogo (estado de emisión/
producción del propio contenido), distinto de "Your status" (estado de
biblioteca del usuario) que aparece unas líneas más abajo en la misma
página — mismo nombre, dos conceptos distintos. Fuera de scope de este
documento resolver esa colisión de naming (posible futura revisión de
copy), pero queda anotado.

`backdrop_url` (imagen de fondo desenfocada tras el header) también es
parcial — movie/series/game la tienen, book no — pero no es un campo de
metadata textual dentro de `buildFields`, es tratamiento visual aparte, así
que no entra en esta tabla de orden.

## Grupo 3 — Específicos (posición 4+, orden interno propio)

| Tipo | Campos específicos (en orden) |
|---|---|
| Movie | `runtime` |
| Series | `number_of_seasons`, `number_of_episodes` |
| Book | `isbn` — **pendiente**: hoy Open Library YA devuelve `isbn` en el mismo `search.json` que se pide (`docs/external-apis.md`, field-set `key,title,author_name,first_publish_year,cover_i,subject,isbn`), pero se descarta — no hay columna en `books` ni mapeo en `book_to_dict` (`backlogg/books/adapters/open_library.py`). Requiere backend primero (feature `book_isbn_field`) antes de poder añadirse aquí. |
| Game | `game_type`, `developer`, `publisher` |

**Movie — `budget`/`revenue` descartados explícitamente**: existen como
columnas en `movies` (`docs/schema.md`) pero nunca se han mostrado en la UI
(`buildFields` no los incluye hoy) y el usuario ha confirmado que no
aportan valor — no se añaden al orden. Quedan en la tabla `movies` sin
exponer, sin que eso sea una carencia a resolver.

**Series — `last_air_date` descartado explícitamente**: el usuario ha
decidido (2026-08-26) quitarlo del detail page. Igual que `budget`/
`revenue` en movie, sigue existiendo como columna en `series`
(`docs/schema.md`) y en `SeriesOut` — solo deja de mostrarse en
`buildFields`, no se elimina del modelo ni de la API.

**Book — `publisher` (editorial) investigado y descartado por ahora**: a
diferencia de `isbn`, la editorial NO está disponible al nivel que se
sincroniza. Open Library solo la expone a nivel de *edition*
(`get_work_detail`, `backlogg/books/adapters/open_library.py:254-282`
confirma que el detalle a nivel *work* no trae publisher), y el modelo
actual es deliberadamente a nivel *work* (`docs/schema.md`: "Modeled at
work level (not edition)"). Añadir editorial exigiría decidir qué edición
usar (¿la primera? ¿la más común?) — más complejo que `isbn`, que ya llega
gratis en la respuesta que se pide hoy. No se incluye en este documento;
si se quiere en el futuro, es una investigación aparte, no parte de esta
feature.

## Orden final propuesto por tipo

- **Movie**: fecha principal → original_language → status → runtime
- **Series**: fecha principal → original_language → status →
  number_of_seasons → number_of_episodes
- **Book**: fecha principal → original_language → isbn *(pendiente de
  backend)*
- **Game**: fecha principal → original_language → game_type → developer →
  publisher
