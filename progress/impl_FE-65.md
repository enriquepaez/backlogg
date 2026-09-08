# Implementación FE-65 — `credits_source_author_writer_display`

Rama: `feat/credits_source_author_writer_display` · id 64 de
`frontend_feature_list.json` (ya estaba en `in_progress`, no lo he cambiado).
Alcance tocado: **solo `apps/web`**. Ni `backlogg/`, ni `tests/`, ni `alembic/`,
ni `packages/api-client/`, ni contrato de API.

## Archivos

| Archivo | Qué y por qué |
|---|---|
| `apps/web/src/lib/credit-role-labels.ts` (nuevo) | `CREDIT_ROLE_CODES` (los 6 roles que el backend puede devolver en `credits[]`) + `creditRoleLabels(t)`, que construye el mapa `role → etiqueta traducida`. Copia deliberada del patrón ya establecido por `src/lib/game-type-labels.ts` (mismo tipo `Translate`, misma idea de "vocabulario de backend traducido en un helper de lib, no en el componente"). |
| `apps/web/src/lib/credit-role-labels.test.ts` (nuevo) | Tests del helper: cobertura de los 6 códigos, claves distintas para `SOURCE_AUTHOR`/`WRITER`, ausencia de entrada para vocabulario desconocido, y **lectura directa de `messages/{en,es}.json`** para fijar que existe copy en los dos idiomas para cada código (criterio 4). |
| `apps/web/src/components/item-credits.tsx` | Nueva prop opcional `roleLabels?: Record<string, string>`; la segunda línea de cada entrada pasa a ser `character_name ?? roleLabels?.[role] ?? role`. Añadido `title` a esa línea (las etiquetas traducidas son más largas que los códigos crudos y la celda tiene `truncate`). Doc comment reescrito: el `role` deja de ser "contenido de catálogo crudo" y pasa a ser vocabulario de backend traducido. |
| `apps/web/src/components/item-credits.test.tsx` | Tests de la feature (detalle abajo). |
| `apps/web/src/app/[locale]/[type]/[slug]/page.tsx` | Import de `creditRoleLabels` y `roleLabels={creditRoleLabels(t)}` en el render de `ItemCredits` (2 líneas). |
| `apps/web/src/app/[locale]/[type]/[slug]/page.test.tsx` | El mock de `ItemCredits` expone ahora `roleLabels` en `data-role-labels`, y un test nuevo fija que la página baja las 6 claves (si no, el cableado no lo cubría nadie). |
| `apps/web/messages/es.json`, `apps/web/messages/en.json` | Bloque nuevo `ItemDetail.credits.roles` con los 6 códigos. Único cambio en cada archivo (ver `git diff`). |

Ruta real de los mensajes: `apps/web/messages/{es,en}.json` (no
`src/i18n/messages/`, que no existe; `src/i18n/request.ts` los carga desde ahí).

## Copy propuesto (a confirmar por el usuario en la QA)

| Código | Español | Inglés | Nota |
|---|---|---|---|
| `ACTOR` | Reparto | Cast | Casi nunca se ve: las entradas de reparto muestran `character_name`. Solo aparece si el personaje llega `null`. |
| `DIRECTOR` | Dirección | Director | Movies. |
| `CREATOR` | Creación | Creator | Series. |
| `WRITER` | **Guion de la adaptación** | **Adaptation screenplay** | Guionista de la adaptación (Fukunaga en *It*). |
| `AUTHOR` | Autoría | Author | Solo libros; hoy la sección Credits no se renderiza para book, se incluye por completitud del vocabulario. |
| `SOURCE_AUTHOR` | **Autoría de la obra original** | **Author of the original work** | Autor de la obra de origen (Stephen King en *It*), no del guion. |

Dos decisiones de copy que conviene mirar en la QA:

1. **En español usé sustantivos de función** ("Dirección", "Creación",
   "Autoría") en lugar de los sustantivos de persona que ya usa el `dl` de
   metadata del hero ("Director", "Creador", "Autor", en
   `ItemDetail.fields.*`). Motivo: en una lista de créditos bajo el nombre de
   la persona, la función es la convención habitual y además es neutra en
   género — "Director" bajo el nombre de una directora chirría. **Coste**: la
   ficha muestra "Director" en el `dl` y "Dirección" en Credits para la misma
   persona. Si el usuario prefiere consistencia literal, el cambio es de
   una línea por idioma en `messages/*.json` y los tests de `item-credits`
   habría que ajustarlos (fijan el string renderizado, a propósito).
2. **`WRITER` = "Guion de la adaptación"**, no "Guion" a secas. El criterio 2
   solo exige claridad en `SOURCE_AUTHOR`, pero la distinción se lee mucho
   mejor con las dos etiquetas explícitas y contrapuestas ("...de la
   adaptación" / "...de la obra original"). Si el título es original (no
   adaptado), TMDB igualmente etiqueta `Screenplay`/`Writer`, así que
   "Guion de la adaptación" puede sonar raro en una película no adaptada.
   Es el trade-off consciente que dejo al criterio del usuario: la alternativa
   es "Guion" / "Screenplay" y confiar todo el peso semántico a la etiqueta de
   `SOURCE_AUTHOR`.

## Decisiones no fijadas en el plan

- **`roleLabels` como prop, no `useTranslations` dentro del componente.**
  `ItemCredits` es puramente presentacional por diseño (`heading` y
  `emptyMessage` ya llegan traducidos desde la página) y la página es quien
  tiene el translator de `ItemDetail`. Se mantiene esa frontera: la página
  construye el mapa con `creditRoleLabels(t)` y lo baja. Además así los tests
  del componente siguen sin necesitar `NextIntlClientProvider` ni mock de
  `next-intl`, como hasta ahora.
- **Prop opcional (`roleLabels?`)**, no obligatoria: si un caller no la pasa, el
  comportamiento es exactamente el de antes (rol crudo). Eso deja intactos los
  tests preexistentes que fijaban el fallback crudo (`developer`, `AUTHOR`) sin
  reescribirlos, y no obliga a inventar un mapa a un caller futuro que no
  traduzca nada.
- **Mapa parcial, sin bucket "other".** `gameTypeLabel` cae a
  `gameTypes.other` ("Otro"), pero aquí ese genérico diría *menos* que el rol
  crudo, así que el fallback es el propio valor del backend — la política
  vigente del componente y lo que pide el punto 2 del encargo.
- **`title` en la línea de rol.** Cambio mínimo de presentación no pedido:
  con `truncate` en un grid de hasta 4 columnas, "Autoría de la obra
  original" se corta. El `title` da el texto completo en hover, igual que ya
  hacía el nombre de la persona.
- **Test extra en `page.test.tsx`.** No estaba en el encargo (que solo pedía
  tests en `item-credits.test.tsx`), pero sin él nada fijaba que la página
  realmente pase `roleLabels`: los tests del componente pasarían igual con el
  cableado roto.

## Tests añadidos

En `item-credits.test.tsx` (además de los 5 que ya había, todos intactos):

- `SOURCE_AUTHOR` y `WRITER` renderizan **dos etiquetas distintas**, una vez
  cada una, ninguna fusionada, y ningún código crudo se escapa a la página;
  además se comprueba que cada etiqueta cuelga de la persona correcta
  (King → obra original, Fukunaga → adaptación).
- El resto del vocabulario (`DIRECTOR`/`CREATOR`/`AUTHOR`) también se traduce
  — fija la decisión de no dejar roles crudos al lado de los traducidos.
- Rol desconocido (`COMPOSER`) → cae al valor crudo.
- Entrada de reparto con `character_name` → sigue mostrando el personaje, no
  la etiqueta de rol.
- Ítem sin credits → ni `<ul>`, ni etiqueta de rol suelta, solo el mensaje
  vacío (criterio 3: nada de encabezado huérfano; la lista sigue **plana**, sin
  subsecciones por rol).

## Verificación

```
$ pnpm --filter web typecheck
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
EXIT=0

$ pnpm --filter web lint
$ eslint
EXIT=0

$ pnpm --filter web test
 Test Files  130 passed (130)
      Tests  1186 passed (1186)
   Duration  49.51s
EXIT=0

$ pnpm --filter web build
$ next build
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully in 227ms
  Running TypeScript ... Finished TypeScript in 2.5s
  Generating static pages ... (69/69)
✓ Build succeeded
EXIT=0
```

(Antes: 1185 tests tras los del componente y el helper; 1186 con el de
cableado en `page.test.tsx`. En `main` había 1181 en `apps/web`.)

Los avisos del `build` — `metadataBase not set` y los `Dynamic server usage`
de rutas `/admin/*` que usan `cookies` — son preexistentes y no los introduce
esta feature.

## Fuera de alcance a propósito

- **No se agrupa por rol** ni se añaden subencabezados: el criterio pide
  etiquetas distintas, no agrupación, y agrupar reabriría el riesgo de
  encabezado huérfano que el criterio 3 prohíbe (decisión ya fijada en
  `progress/current.md`).
- **No se toca el orden de `credits[]`**: sigue llegando del backend (reparto
  por `billing_order`, luego crew) y se pinta tal cual.
- **Book y game siguen sin sección Credits.** `AUTHOR` está traducido por
  completitud del vocabulario, pero hoy solo movie/series renderizan
  `ItemCredits` (`docs/detail-page-layout.md`); no he cambiado esa condición.
- **No hay enlace a ficha de persona** (no existe esa feature todavía).
- **Sin cambios en `packages/api-client`** ni en el contrato: la feature no
  añade campos, solo presentación. No hace falta gate de regeneración.
- **`bruno/`**: no aplica, no se ha creado, modificado ni eliminado ningún
  endpoint.

## Nota para el reviewer / QA

Para ver los dos roles a la vez hace falta un ítem adaptado: p. ej. una
película con `SOURCE_AUTHOR` y `WRITER` en `credits[]`
(`GET /v1/movies/{slug}` en producción). En `es` deben leerse "Autoría de la
obra original" y "Guion de la adaptación" en entradas separadas, nunca la
misma etiqueta dos veces.

---

# Ajuste tras la decisión del usuario

Segunda pasada sobre la misma rama, **después del `APPROVED`** de
`progress/review_FE-65.md`. No es un rechazo: el usuario cambió el alcance de
la sección Credits («los credits no deben incluir dirección, el director va en
el hero» · «todo esto debería ser mucho más simple. Director en el hero y
actores en credits», opción B). Todo lo de arriba sigue describiendo el estado
anterior; esta sección describe lo que cambia respecto a él. Alcance: **solo
`apps/web`** (verificado con `git status --short`: cero cambios en `backlogg/`,
`tests/`, `alembic/`, `packages/api-client/`, `bruno/`; `docs/` lo edita el
leader, yo no lo he tocado).

## Qué cambia

| # | Cambio | Dónde |
|---|---|---|
| 1 | `DIRECTOR`/`CREATOR` salen de la sección Credits | `page.tsx` → `getCredits` |
| 2 | `WRITER` = «Guion» / «Screenplay» | `messages/{es,en}.json` |
| 3 | `SOURCE_AUTHOR` intacto | — |
| 4 | Vocabulario reducido a 4 códigos + constante `HERO_ROLES` | `credit-role-labels.ts`, `messages/*` |
| 5 | La sección no se monta si la lista filtrada queda vacía | `page.tsx` (render) |
| O-4 | `roleLabels` pasa a obligatoria | `item-credits.tsx` |

## Archivos tocados en esta pasada

| Archivo | Qué |
|---|---|
| `apps/web/src/lib/credit-role-labels.ts` | Nueva constante exportada `HERO_ROLES = ["DIRECTOR", "CREATOR"]` con el porqué documentado (esos dos ya salen en el `dl` del hero, posición 2 de `docs/detail-page-layout.md`). `CREDIT_ROLE_CODES` baja de 6 a 4: `ACTOR`, `WRITER`, `AUTHOR`, `SOURCE_AUTHOR`. Los dos doc comments dicen explícitamente que las dos listas son **disjuntas** y por qué. |
| `apps/web/src/lib/credit-role-labels.test.ts` | Test de vocabulario reescrito a los 4 códigos; test nuevo de disyunción (`HERO_ROLES` no tiene etiqueta y no está en `CREDIT_ROLE_CODES`); test nuevo que **fija el copy literal** de `WRITER`/`SOURCE_AUTHOR` en los dos idiomas. El test de paridad (`Object.keys(roles)` vs `CREDIT_ROLE_CODES`) no cambia de forma: sigue reventando si sobra o falta copy — ahora contra 4 claves, lo que es justo lo que detecta el copy muerto. |
| `apps/web/src/components/item-credits.tsx` | `roleLabels: Record<string, string>` **obligatoria** (`roleLabels?.[…]` → `roleLabels[…]`), con el argumento del reviewer escrito en el doc comment de la prop. Párrafo nuevo en el doc del componente: qué cubre la sección (reparto + guion + autoría de la obra original), que director/creador se filtran **en la página** y que el componente no sabe nada de esa decisión de layout. |
| `apps/web/src/components/item-credits.test.tsx` | `roleLabels` pasada en los 4 renders que la omitían; mapa de prueba a 4 entradas con el copy nuevo; el antiguo test «traduce DIRECTOR/CREATOR» se convierte en su contrario (no hay etiqueta para ellos y, si uno se colara, degrada al código crudo). |
| `apps/web/src/app/[locale]/[type]/[slug]/page.tsx` | `getCredits` filtra `HERO_ROLES`; render condicionado a `credits.length > 0`; `getCredits(item)` se calcula una vez en una `const credits`. |
| `apps/web/src/app/[locale]/[type]/[slug]/page.test.tsx` | Mock de `ItemCredits` con `roleLabels` obligatoria y `data-credits` (para asertar sobre lo que la página **entrega**); fixture compartida `castCredit`; bloque `describe` nuevo con los tests del filtrado y del ocultado. |
| `apps/web/messages/{es,en}.json` | `WRITER` reescrito; claves `DIRECTOR` y `CREATOR` borradas. |

## Decisiones de esta pasada

- **El filtro va en `getCredits`, no en `ItemCredits`.** Lo pedía el encargo y
  además es lo correcto por capas: la página es la única que sabe qué pinta el
  hero. Está escrito en el doc comment de `getCredits`, citando la decisión del
  usuario en su literal.
- **`HERO_ROLES` es una constante exportada, no dos strings inline.** Así la
  relación «esto sale del hero → por eso no va en Credits» está en el código, y
  el test de disyunción puede afirmarla. Vive en `credit-role-labels.ts`, junto
  a `CREDIT_ROLE_CODES`, porque las dos son las mitades de la misma partición
  del vocabulario: tenerlas separadas invitaría a que divergieran.
- **`AUTHOR` no entra en `HERO_ROLES`** aunque también salga en el `dl` del
  hero (libros). Motivo: book **no renderiza** la sección Credits, así que
  filtrarlo sería código muerto que además dejaría el vocabulario sin `AUTHOR`
  el día que la sección se extienda. Anotado en el doc comment.
- **`heroRoles: readonly string[]` local en `getCredits`.** `HERO_ROLES` es un
  tuple `as const`, y `.includes(credit.role)` sobre un `readonly ["DIRECTOR",
  "CREATOR"]` no acepta un `string` cualquiera. La alternativa era ensanchar el
  tipo de la constante y perder la literalidad que el test aprovecha; una línea
  local es más barata.
- **`emptyMessage` se sigue pasando** aunque el caller ya no monte el
  componente con lista vacía: el componente conserva su estado vacío como ruta
  degradada ante `credits: undefined` (el bug real de `progress/history.md`), y
  la clave `credits.empty` sigue por tanto viva y usada. No la he borrado.
- **`ItemPlatforms` intacto**, y con un test que lo fija (un game sin
  plataformas sigue mostrando sección + mensaje vacío). La divergencia es
  consciente: una ausencia de plataformas es información; un «no hay créditos»
  bajo un hero que nombra al director, no.

## Tests

`page.test.tsx`, bloque nuevo «Credits excludes the roles the hero already
shows (FE-65)»:

- movie: con `ACTOR` + `DIRECTOR` + `WRITER` + `SOURCE_AUTHOR` en `credits[]`,
  la página entrega exactamente `ACTOR`, `WRITER`, `SOURCE_AUTHOR` — y en ese
  orden (el filtro no reordena).
- series: con `CREATOR` + `ACTOR`, entrega solo `ACTOR`.
- **Ítem cuyo único credit era `DIRECTOR` → la sección no se monta**: ni
  encabezado ni mensaje vacío (`querySelector('[data-testid="item-credits"]')`
  es `null`).
- movie/series sin ningún credit → tampoco se monta.
- game sin plataformas → `ItemPlatforms` **sí** se monta, con su
  `platformsEmpty`.

Ajustados además: el test de claves de `roleLabels` (6 → 4, sin `DIRECTOR`/
`CREATOR`), los tres tests que asumían sección presente con `credits: []`
(ahora reciben `castCredit`), y los de copy en `item-credits.test.tsx` y
`credit-role-labels.test.ts`.

Se mantienen sin cambios de intención los que ya eran válidos: personaje sobre
etiqueta de rol, fallback a rol crudo para vocabulario desconocido, lista plana
y degradación ante `credits: undefined`.

Recuento: 1186 → **1193** tests en `apps/web` (130 archivos, mismo número).

## Verificación (los cuatro en verde)

```
$ pnpm --filter web typecheck
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
EXIT=0

$ pnpm --filter web lint
$ eslint
EXIT=0

$ pnpm --filter web test
$ vitest run
 RUN  v4.1.10 /home/enriquepaez/projects/backlogg/apps/web
 (ExperimentalWarning: localStorage is not available… × N workers — preexistente)

 Test Files  130 passed (130)
      Tests  1193 passed (1193)
   Duration  27.62s (transform 6.34s, setup 67.98s, import 26.63s,
                     tests 54.20s, environment 111.90s)
EXIT=0

$ pnpm --filter web build
$ next build
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully
  Running TypeScript ... Finished TypeScript
  Generating static pages (69/69)
ƒ Proxy (Middleware)
○  (Static)   prerendered as static content
●  (SSG)      prerendered as static HTML (uses generateStaticParams)
ƒ  (Dynamic)  server-rendered on demand
EXIT=0
```

Ejecución focalizada de los tres archivos tocados:

```
$ pnpm vitest run src/lib/credit-role-labels.test.ts \
    src/components/item-credits.test.tsx \
    'src/app/[locale]/[type]/[slug]/page.test.tsx'
 Test Files  3 passed (3)
      Tests  78 passed (78)
EXIT=0
```

Los avisos de `build` (`metadataBase not set`, `Dynamic server usage` en rutas
`/admin/*` que leen `cookies`) siguen siendo los preexistentes.

## Paridad es/en, recomprobada tras borrar dos claves

```
en 785 · es 785 · only-en [] · only-es []
```

(Recuento de rutas de clave completas, nodos intermedios incluidos — de ahí la
diferencia con las 652 hojas que contó el reviewer. Lo relevante es la
diferencia simétrica vacía.) Ambos JSON parsean. `grep` de
`credits.roles.DIRECTOR`, `credits.roles.CREATOR`, `"Adaptation screenplay"` y
`"Guion de la adaptación"` en `apps/web/src` y `apps/web/messages`: **cero
resultados**, no queda copy muerto ni referencias colgadas.

## Lo que sigue igual

Lista plana sin agrupar ni subencabezados · `character_name` manda sobre la
etiqueta de rol · fallback al rol crudo para vocabulario desconocido · book y
game siguen sin sección Credits · sin enlace a ficha de persona · sin cambios
en `packages/api-client` ni en el contrato (no aplica el gate de regeneración)
· `bruno/` no aplica (ningún endpoint creado, modificado ni eliminado).

## Nota para la QA

El caso interesante ahora es un ítem cuyo único credit era el director: la
sección Credits **debe desaparecer entera**, no mostrar «Créditos» + «No hay
información de créditos disponible». En la DB de dev eso son 13 movies de 596 y
25 series de 1.142. Y en una película adaptada deben leerse «Guion» y «Autoría
de la obra original» en entradas separadas, sin ninguna fila de dirección
duplicando lo que ya dice el hero.
