# Detail page layout — orden de los campos de metadata

> Decidido con el usuario el 2026-08-26/27, implementado en
> `apps/web/src/app/[locale]/[type]/[slug]/page.tsx` (`buildFields`, feature
> frontend FE-64). Este documento es la fuente de verdad del *orden*; el
> código es la fuente de verdad una vez implementado — si divergen,
> actualiza este archivo. Varias rondas de corrección — ver
> `progress/history.md` para el detalle de cada una.

## Contexto

Las 4 detail pages (movie/series/book/game) comparten un bloque de "campos
de metadata" (`buildFields` en `page.tsx`). Dos principios gobiernan qué
aparece y en qué orden:

1. Un campo que la API de origen de un tipo **nunca** puede rellenar
   (estructuralmente, no solo "falta en este item") se omite de
   `buildFields` para ese tipo — no se muestra con placeholder.
2. El campo "quién es responsable" (director/creator/author/developer) va
   **siempre en la posición 2**, justo después de la fecha, en los 4
   tipos — es el único concepto, aparte de la fecha, que se repite en los
   4 con el mismo peso, así que es el que más vale la pena fijar en el
   mismo sitio visual.

## Orden final por tipo

| Pos | Movie | Series | Book | Game |
|---|---|---|---|---|
| 1 | Release date | First aired | First published | Release date |
| 2 | **Director** | **Creator** | **Author** | **Developer** |
| 3 | Status | Status | ISBN | Publisher |
| 4 | Runtime | Seasons | — | Type |

- **Movie**: release_date → director → status → runtime
- **Series**: first_air_date → creator → status → number_of_seasons
- **Book**: first_publish_date → author → isbn
- **Game**: release_date → developer → publisher → game_type

## "Quién es responsable" (posición 2) — de dónde sale cada uno

Todos vienen de `credits` (personas) salvo game, que viene de `companies`
(compañías vía `company_credits`, feature backend 67, ya done):

- **Movie → `director`**: `credits` con `role: "DIRECTOR"`
  (`backlogg/movies/service.py` — TMDB crew filtrado a `job == "Director"`).
- **Series → `creator`**: `credits` con `role: "CREATOR"`
  (`backlogg/series/service.py` — campo `created_by` de TMDB). Se eligió
  creator y no director porque las series raramente acreditan un único
  director (comentario explícito en `series/service.py`), a diferencia de
  una película.
- **Book → `author`**: `credits` con `role: "AUTHOR"` — el único rol que
  existe para books (`docs/schema.md`).
- **Game → `developer` + `publisher`**: dos filas, no una — mismo concepto
  pero repartido en dos roles distintos de `company_credits`
  (`companiesByRole`), a diferencia de los otros 3 tipos donde es una sola
  fila (`peopleByRole`).

Puede haber más de un nombre por fila (coautoría, codirección, dos
creadores) — se unen con coma.

Este campo vive **dentro** del `dl` de metadata, junto al resto — no en
una sección aparte. Es distinto y más estrecho que la sección "Credits"
completa (ver más abajo): un nombre (o un par), no el reparto entero.

## Campos omitidos por completo (no solo sin placeholder)

- **`original_language`** (los 4 tipos): decisión del usuario (2026-08-27)
  de quitarlo en todos los tipos, incluidos movie/series donde sí había
  dato real de TMDB — simplificación deliberada, no una limitación de la
  fuente en esos 2 casos. En book/game sí era además una limitación real:
  Open Library no tiene idioma a nivel de *work* (`docs/schema.md`), IGDB
  no modela "idioma original" como concepto. El campo sigue en el schema/
  DB/API de los 4 tipos — es una omisión solo de la UI.
- **`number_of_episodes`** (series): decisión del usuario (2026-08-27) de
  quedarse solo con `number_of_seasons`. Sigue en `SeriesOut`/DB.
- **`status`** (release/production status — RELEASED/RETURNING/...): no
  existe como concepto en book/game (no hay equivalente de "estado de
  emisión/producción" para un libro o un juego en este schema), así que
  la fila no aparece para esos 2 tipos.

Nota: `status` es un concepto de catálogo (estado de emisión/producción
del propio contenido), distinto de "Your status" (estado de biblioteca del
usuario) que aparece unas líneas más abajo en la misma página — mismo
nombre, dos conceptos distintos. Fuera de scope de este documento resolver
esa colisión de naming (posible futura revisión de copy), pero queda
anotado.

`backdrop_url` (imagen de fondo desenfocada tras el header) es parcial —
movie/series/game la tienen, book no — pero no es un campo de metadata
textual dentro de `buildFields`, es tratamiento visual aparte, así que no
entra en esta tabla de orden.

## Campos descartados de la UI explícitamente (siguen en el modelo/API)

- **Movie — `budget`/`revenue`**: nunca se han mostrado en la UI
  (`buildFields` no los incluyó nunca) y el usuario confirmó que no
  aportan valor.
- **Book — `publisher` (editorial)**: investigado y descartado — Open
  Library solo la expone a nivel de *edition*
  (`get_work_detail`, `backlogg/books/adapters/open_library.py:254-282`),
  no a nivel *work* (que es como está modelado el libro). Añadirlo
  exigiría decidir qué edición usar — más complejo que `isbn`, que ya
  llegaba gratis en la respuesta que se pedía. Investigación aparte si se
  quiere en el futuro.

## Sección "Credits" (lista completa de cast/crew) — solo movie/series

Distinto del campo "quién es responsable" de arriba: esta es la sección
aparte (`ItemCredits`, tras "Reviews") con el reparto completo. Solo se
renderiza para movie/series. Book no la lleva — su único rol (`AUTHOR`) ya
está cubierto por el campo del `dl`, una sección aparte para uno o dos
nombres sería redundante. Game tampoco — no tiene datos de person-credits
(la feature backend `catalog_credits_ingestion_parity` sigue pendiente y
no añade ninguno) y developer/publisher ya cubren "quién lo hizo" vía
company_credits.

## Orden de secciones de la página (no solo del `dl` de metadata)

Decisión del usuario (2026-08-27): justo debajo del bloque de info (hero:
poster, título, metadata, géneros, rating, botones de estado), antes de
"Your rating"/"Reviews", va una sección type-dependent:

| Tipo | Sección justo debajo de la info |
|---|---|
| Movie | Credits (cast/crew completo) |
| Series | Credits (cast/crew completo) |
| Book | *(nada)* |
| Game | Platforms |

Orden completo de la página: Hero → [Credits \| Platforms \| nada] → Your
rating → Reviews → You might also like.

`Platforms` (`ItemPlatforms`, componente nuevo) vivía antes dentro de
`ItemHero` como una fila de badges más (FE-60, junto a los géneros). Se
extrajo a su propia sección con la misma forma que `ItemCredits`
(`section`/`h2`/estado vacío) para poder ocupar este mismo hueco — mismos
badges coloreados por familia de consola
(`platformFamily`/`PLATFORM_COLOR_CLASSES`,
`lib/game-platform-colors.ts`), solo que ahora en su propia sección en vez
de embebidos en el hero.
