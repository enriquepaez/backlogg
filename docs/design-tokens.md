# Design tokens — colores de estado y tipo de producto

> Paleta acordada con el usuario el 2026-08-25, pendiente de implementación en
> `apps/web/src/app/globals.css` (feature frontend futura). Este documento es
> la fuente de verdad del *diseño*; el CSS es la fuente de verdad del
> *código* una vez implementado — si divergen, actualiza este archivo.

## Contexto

Dos sistemas de color conviven en la misma tarjeta de catálogo:
- **Status** (`want`/`in_progress`/`completed`/`dropped`) — estado de biblioteca del usuario.
- **Type** (`movie`/`series`/`book`/`game`) — tipo de producto, badge superpuesto al póster.

Más `--accent`/`--primary` (violeta, marca del producto, ya existente — no se toca).

## Principios de diseño

1. **Mapeo mental natural para status**: rojo = eliminado/parada, verde = completado/éxito,
   azul = pendiente/futuro (sin urgencia), amarillo = en curso/precaución. Es el único
   sistema con semántica fija — no cambia aunque el resto del branding evolucione.
2. **Psicología del medio para type**: cada tipo evoca su medio (ver tabla) sin imitar
   directamente el logo de una plataforma de streaming conocida.
3. **Vivos y sólidos, no pastel** — mismo criterio que el resto de la app.
4. **Texto blanco por defecto**; texto negro solo donde el color de fondo no puede ser
   suficientemente oscuro sin perder su identidad (amarillo, cian) — la excepción está
   documentada por color, no es un criterio ad-hoc.
5. **Separación real en la rueda de color**, no solo "distinto del vecino más cercano".
   Los 9 colores se distribuyeron por ángulo de hue (OKLCH) para evitar huecos vacíos en
   una zona y amontonamiento en otra — ver "Proceso" más abajo.

## Paleta (tema claro)

| Rol | Hex | OKLCH | Texto | Evoca |
|---|---|---|---|---|
| Accent (marca, sin tocar) | `#7020e6` | `oklch(0.50 0.259 291.9)` | blanco | — |
| Dropped | `#dc2626` | `oklch(0.577 0.215 27.3)` | blanco | parada, alerta, eliminado |
| Completed | `#15803d` | `oklch(0.527 0.137 150.1)` | blanco | éxito, avance |
| Want | `#2563eb` | `oklch(0.546 0.215 262.9)` | blanco | pendiente, frío, sin urgencia |
| In progress | `#facc15` | `oklch(0.861 0.173 91.9)` | **negro** | energía, "trabajando" |
| Movie | `#0f766e` | `oklch(0.511 0.086 186.4)` | blanco | teal & orange grading, cine premium |
| Series | `#a81487` | `oklch(0.501 0.206 340.0)` | blanco | cultura pop, streaming, neón |
| Book | `#8d3613` | `oklch(0.45 0.127 40.0)` | blanco | papel, cuero, madera, calidez |
| Game | `#26c0e9` | `oklch(0.751 0.131 221.7)` | **negro** | LED/RGB, ciberespacio, electricidad |

**Tema oscuro**: pendiente de derivar en implementación, mismo método que el bloque
`--status-*` ya existente en `globals.css` (fondo brillante + texto oscuro para todos,
gamut-sweep OKLCH→sRGB con margen de seguridad, contraste WCAG re-verificado contra la
superficie oscura — no asumas que basta con invertir L).

## Excepciones de texto (por qué solo 2 de 9)

- **In progress** (amarillo): ningún amarillo lo bastante oscuro para texto blanco legible
  sigue leyéndose como "amarillo" — se vuelve marrón. Texto negro es la única opción viable.
- **Game** (cian): mismo problema en la región azul-cian-verde del círculo — a la
  luminosidad que da buen contraste con texto blanco, esa franja de hue tiene un techo de
  chroma en sRGB demasiado bajo para leerse "vivo" (confirmado por barrido de gamut).
  Empujar el chroma hacia arriba obliga a subir también la luminosidad, lo que a su vez
  obliga a texto negro.
- El resto (7 de 9) usa texto blanco de forma uniforme.

## Trade-offs aceptados

Validado con simulación de daltonismo real (protanopia/deuteranopia, matrices
Machado–Oliveira–Fernandes 2009) — no solo contraste WCAG. Ningún par colapsa
(ΔE por debajo de 4 en visión no simulada); los siguientes quedan por debajo del objetivo
ideal pero se consideran aceptables porque **todo badge de esta paleta siempre lleva
texto visible junto al color** (la mitigación que exige cualquier metodología de paleta
categórica cuando un par queda en la banda de aviso):

- `dropped` ↔ `book` — ambos cálidos, terracota y rojo comparten familia de hue.
- `movie` ↔ `series` — colapsan bajo simulación de deuteranopia específicamente (ΔE 3.9),
  pero se leen completamente distintos en visión normal (ΔE 28.6).
- `completed` ↔ `movie` — verde oscuro y teal oscuro, familias de hue adyacentes.
- `want` ↔ `accent` — azul y violeta, separación moderada.

## Proceso (para referencia futura, si hay que retocar esta paleta)

1. Partir de los 4 hues canónicos de status (rojo/verde/azul/amarillo) — no negociables.
2. Fijar `accent` (violeta, marca, ya existente).
3. Distribuir los 4 hues de type por los huecos *reales* en la rueda de 360°, no solo
   evitando el vecino más próximo — un hueco grande sin usar en un lado de la rueda y dos
   colores apretados en un hueco pequeño en el otro lado es el error más común (pasó dos
   veces en esta sesión: `game` quedó primero pegado a `completed`, luego a `accent`/`want`,
   hasta que se movió al hueco de 76° que quedaba vacío entre `movie` y `want`).
4. Para cada hue, buscar la luminosidad que da croma casi-máximo en gamut sRGB — no asumir
   una luminosidad compartida para todos: hay una franja del círculo (azul-cian, ~170-250°)
   donde el techo de chroma es bajo a luminosidad oscura y solo mejora subiendo mucho la
   luminosidad (de ahí las 2 excepciones de texto negro).
5. Validar con simulación CVD real (no solo WCAG), aceptando la banda de aviso (no el
   colapso) cuando el texto acompañante mitiga el riesgo.
