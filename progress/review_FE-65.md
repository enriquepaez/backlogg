# Review — FE-65 `credits_source_author_writer_display` (id 64)

**APPROVED**

Re-review sobre `feat/credits_source_author_writer_display`, 2026-09-08.
Revisado el working tree completo (`git diff main` + los tres archivos sin
trackear: `apps/web/src/lib/credit-role-labels.ts`, `.test.ts` y
`progress/impl_FE-65.md`). La rama sigue **sin commits** por encima de `main`
(`git log main..HEAD` vacío): el veredicto se emite sobre el árbol de trabajo.

## Nota de historia de este archivo

Este documento **sustituye** al veredicto anterior. Hubo un primer `APPROVED`
sobre una versión distinta de la feature (Credits con los 6 roles del
vocabulario, `DIRECTOR` = «Dirección», `CREATOR` = «Creación», `WRITER` =
«Guion de la adaptación», sección siempre visible con mensaje vacío,
`roleLabels` opcional). Tras aquella aprobación el usuario cambió el alcance
(«los credits no deben incluir dirección, el director va en el hero» ·
«Director en el hero y actores en credits»), el leader lo concretó en
`progress/current.md` → «Cambio de alcance del usuario» y en
`docs/detail-page-layout.md` → «Credits», y el implementer reelaboró. Lo que
cambia respecto a la versión aprobada antes:

1. `DIRECTOR`/`CREATOR` se filtran en `getCredits` (página), no llegan a la
   sección.
2. `WRITER` = «Guion» / «Screenplay» (sin «de la adaptación»).
3. `SOURCE_AUTHOR` intacto.
4. Claves `DIRECTOR`/`CREATOR` borradas de `messages/{es,en}.json` y de
   `CREDIT_ROLE_CODES` (6 → 4 códigos).
5. La sección no se monta si la lista filtrada queda vacía.
6. `roleLabels` pasa a obligatoria (era la observación O-4 de la review
   anterior).

Ninguna de las observaciones no bloqueantes de la primera review queda viva:
O-1 (copy de `WRITER`) la resolvió el usuario, O-4 (`roleLabels` opcional) está
implementada.

---

## Criterios de aceptación (`frontend_feature_list.json`, id 64)

### 1. `SOURCE_AUTHOR` y `WRITER` con etiquetas distintas y traducidas (es/en), nunca fusionadas — **CUMPLE**

`apps/web/src/components/item-credits.tsx:91-92`:

```ts
const secondaryLine =
  credit.character_name ?? roleLabels[credit.role] ?? credit.role;
```

Copy en los dos idiomas (`apps/web/messages/{es,en}.json` →
`ItemDetail.credits.roles`):

| Código | es | en |
|---|---|---|
| `WRITER` | Guion | Screenplay |
| `SOURCE_AUTHOR` | Autoría de la obra original | Author of the original work |

Fijado a dos niveles: copy literal en `credit-role-labels.test.ts:84-89` (los
cuatro strings, en `en` y `es`) y render en `item-credits.test.tsx` («labels
SOURCE_AUTHOR and WRITER with distinct translated labels, never merged under
one»: una ocurrencia de cada etiqueta, ningún código crudo en la página, y cada
etiqueta colgando de la persona correcta vía `parentElement`).

### 2. La etiqueta de `SOURCE_AUTHOR` deja claro que es autoría de la obra de origen — **CUMPLE**

«Autoría de la obra original» / «Author of the original work»: nombra la obra
de origen y no contiene guion/screenplay. Coherente con `docs/schema.md`,
«`SOURCE_AUTHOR` vs `WRITER`». `credit-role-labels.test.ts:69-77` exige además
`SOURCE_AUTHOR !== WRITER` y `SOURCE_AUTHOR !== AUTHOR` en los dos locales.

### 3. Un ítem sin ninguno de los dos roles no muestra sección vacía ni encabezado huérfano — **CUMPLE, y ahora más fuerte**

`page.tsx:514`: `{(type === "movie" || type === "series") && credits.length > 0 && (`.
La lista sigue plana (sin subencabezados por rol, así que no hay encabezado que
pueda quedar huérfano) y además la sección entera desaparece cuando no queda
nada que pintar. Tests en `page.test.tsx`: «renders no section at all — no
heading, no empty message — when the only credit was the director» y «renders
no section at all for a movie/series with no credits whatsoever», ambos
asertando `container.querySelector('[data-testid="item-credits"]')` a `null`.

### 4. Sin strings hardcodeados: claves next-intl en `es.json` y `en.json` — **CUMPLE**

`creditRoleLabels(t)` (`credit-role-labels.ts:64-68`) construye el mapa desde
`credits.roles.<CODE>`; el componente recibe todo pretraducido, igual que
`heading`/`emptyMessage`. `page.test.tsx` («passes the translated credit-role
labels down, one key per renderable role») fija el cableado: sin ese test, el
componente pasaría verde con la página rota.

### 5. Test que fija las etiquetas de ambos roles y su separación — **CUMPLE**

`credit-role-labels.test.ts` (8 casos) + los 5 nuevos de
`item-credits.test.tsx` + el bloque nuevo de `page.test.tsx`.

### 6. `typecheck && lint && build && test` en verde — **CUMPLE**

Ver «Salida de los comandos». Los cuatro con exit code real capturado (no el
de un `tail` al final de un pipe). `bash init.sh` también verde: 1499 tests de
backend.

---

## Los seis cambios encargados en esta pasada

| # | Encargo | Estado | Evidencia |
|---|---|---|---|
| 1 | `DIRECTOR`/`CREATOR` filtrados en `getCredits`, con constante explícita | ✅ | `page.tsx:357-359` (`heroRoles.includes`), constante `HERO_ROLES` en `credit-role-labels.ts:22`. El filtro **no** está en `ItemCredits`, que sigue presentacional |
| 2 | `WRITER` = «Guion» / «Screenplay» | ✅ | `messages/{es,en}.json`, fijado en `credit-role-labels.test.ts:84-89` |
| 3 | `SOURCE_AUTHOR` sin cambios | ✅ | mismo copy que en la versión aprobada antes |
| 4 | Claves `DIRECTOR`/`CREATOR` borradas y fuera de `CREDIT_ROLE_CODES` | ✅ | `CREDIT_ROLE_CODES = ["ACTOR","WRITER","AUTHOR","SOURCE_AUTHOR"]`; `grep` de `roles.DIRECTOR`/`roles.CREATOR`/«Dirección»/«Creación»/«Adaptation screenplay»/«Guion de la adaptación» en `apps/web/src` y `apps/web/messages`: **cero** |
| 5 | Sección no renderizada si queda vacía; `ItemPlatforms` intacto | ✅ | `page.tsx:514` + test de que un game sin plataformas **sí** conserva sección y `platformsEmpty` |
| 6 | `roleLabels` obligatoria | ✅ | `item-credits.tsx:28` (`roleLabels: Record<string, string>`, sin `?`) y acceso directo `roleLabels[credit.role]`. Un caller que la omita no compila — `typecheck` verde con el único caller pasándola |

---

## Verificaciones puntuales pedidas

**`DIRECTOR`/`CREATOR` no pueden llegar al render.** Único punto de render de
`ItemCredits` es `page.tsx:514-520`, alimentado por `const credits =
getCredits(item)` (`page.tsx:469`), que filtra. `grep` confirma que no hay otro
caller del componente en `apps/web/src`. Fijado por `page.test.tsx` → «movie:
drops DIRECTOR, keeps cast/WRITER/SOURCE_AUTHOR» (aserta la lista exacta
**y su orden**, así que también fija que el filtro no reordena) y «series:
drops CREATOR, keeps the rest», ambos sobre `data-credits`, es decir sobre lo
que la página **entrega**, no sobre lo que el componente pinta. Correcto: es
donde vive la decisión.

**El hero no se ve afectado.** `buildFields` sigue leyendo `item.credits`
crudo (`page.tsx:178`, `:198`, `:218` vía `peopleByRole`), no `getCredits`, y
`.filter` no muta. Los tests preexistentes `page.test.tsx:557` y `:717` siguen
fijando que el director aparece en el `dl`. Las dos mitades de «director en el
hero, actores en credits» están cubiertas.

**Ítem cuyo único credit era `DIRECTOR`.** Sección ausente por completo, con
test dedicado (arriba, criterio 3).

**Paridad es/en.** Comprobada por mi cuenta contra `main`, no contra la
versión intermedia: 650 hojas en cada locale, diferencia simétrica vacía. Delta
respecto a `main`: `+ItemDetail.credits.roles.{ACTOR,AUTHOR,SOURCE_AUTHOR,WRITER}`
en **ambos** archivos, **cero claves eliminadas** en ambos. Es decir, el borrado
de `DIRECTOR`/`CREATOR` fue un borrado de claves que solo existían en el árbol
de trabajo de esta rama, no arrastró ninguna clave preexistente, y quedó
simétrico. Los dos JSON parsean.

**Copy muerto.** El test `has %s copy for every role code`
(`credit-role-labels.test.ts:60-67`) aserta
`Object.keys(roles).sort() === CREDIT_ROLE_CODES.sort()` contra los JSON
reales: una clave de sobra en `messages` o un código sin copy revientan. Es el
guardarraíl correcto para que esto no se repita. Ver O-1 sobre `AUTHOR`.

**Fallback y prioridad de `character_name`.** Intactos (`item-credits.tsx:91-92`),
con test cada uno: `COMPOSER` → «COMPOSER» crudo, y Chalamet → «Paul Atreides»
y no «Cast». Además hay un test nuevo que fija que `DIRECTOR`/`CREATOR`, si
alguno se colara, **degradan al código crudo** en vez de desaparecer.

**Contra `docs/detail-page-layout.md` (fuente de verdad del layout).** Sin
divergencias. La tabla de roles del doc (`ACTOR` sí, `SOURCE_AUTHOR` sí,
`WRITER` sí, `DIRECTOR` no, `CREATOR` no, `AUTHOR` «no llega»), la ubicación
del filtro en `getCredits`, la constante explícita, el copy «Guion» a secas, el
ocultado de la sección vacía y la divergencia consciente con `ItemPlatforms`
están todos implementados tal cual.

**Alcance.** `git status --short`: solo `apps/web/` (6 archivos) más `docs/`,
`progress/` y `frontend_feature_list.json`, que son del leader. Cero cambios en
`backlogg/`, `tests/`, `alembic/`, `packages/api-client/`, `bruno/`. No aplica
el gate de regeneración de `api-client` (no se toca el contrato) ni el de
`bruno/` (ningún endpoint creado, modificado ni eliminado).

---

## Dictamen sobre los dos puntos abiertos

### A) `AUTHOR` fuera de `HERO_ROLES` — **compro la decisión, con una salvedad**

Compro el argumento tal como está: `HERO_ROLES` solo lo consume `getCredits`, y
`getCredits` solo se ejecuta bajo `type === "movie" || type === "series"`; por
`docs/schema.md` («Supported roles by domain», l. 465-472) `AUTHOR` solo existe
para books. Meterlo en la lista sería una rama que ningún dato puede tomar. Y
`docs/detail-page-layout.md` ya dictaminó exactamente eso en su tabla
(`AUTHOR` → «No llega»), así que el código coincide con la fuente de verdad. La
simetría literal («todo lo que salga en el hero va en `HERO_ROLES`») sería más
bonita como enunciado, pero `HERO_ROLES` no es un catálogo de lo que pinta el
hero: es el filtro de una lista concreta. No hay nada que cambiar.

**La salvedad** es la otra mitad: el motivo que el implementer escribe para
mantener `AUTHOR` **dentro de `CREDIT_ROLE_CODES`** (`credit-role-labels.ts:19-20`,
«remains part of the renderable vocabulary for the day the section is
extended») se contradice con la regla que esta misma feature acaba de
establecer. El día que Credits se extienda a books, `AUTHOR` será justo lo que
el hero ya muestra en la posición 2 (`docs/detail-page-layout.md`), así que la
regla «nada que ya salga en el hero se repite aquí» lo mandaría a `HERO_ROLES`,
no le daría etiqueta. En cualquiera de los dos futuros,
`ItemDetail.credits.roles.AUTHOR` es copy que hoy no puede pintarse: la misma
categoría que las claves `DIRECTOR`/`CREATOR` que esta pasada borró. Es la
única esquina donde «no queda copy muerto» no se cumple del todo. **No
bloquea** (efecto visible cero, y el doc lo bendice), pero ver O-1.

### B) `emptyMessage` y la clave `credits.empty` — **defendible; la justificación escrita, no**

Mantenerlo es correcto: `emptyMessage` es prop **obligatoria** de
`ItemCreditsProps` y el componente conserva su rama vacía con test propio, así
que la clave está en uso desde el punto de vista del tipo. Quitarla exigiría o
hacer la prop opcional o eliminar la rama vacía — un refactor mayor que además
borraría una defensa real. Se queda.

Ahora, el argumento tal como está escrito en `progress/impl_FE-65.md`
(«el componente conserva su estado vacío como ruta degradada ante
`credits: undefined` … y la clave `credits.empty` sigue por tanto viva y
usada») es factualmente flojo en dos puntos:

1. `getCredits` ya normaliza `undefined` a `[]` (`page.tsx:359`, el `?? []`) y
   el render está condicionado a `credits.length > 0`. Desde esta página el
   componente **no puede** recibir ni `undefined` ni lista vacía. Lo que cubre
   el bug de `progress/history.md` es el `credits ?? []` interno del propio
   componente (`item-credits.tsx:76`), que es independiente de que la página
   pase `emptyMessage`.
2. «usada» es inexacto: la clave se **pasa**, nunca se **renderiza** desde esta
   página. El propio test lo reconoce («The page no longer mounts this
   component with an empty list»).

Lo correcto es lo que dice el test, no lo que dice el `impl_`: es una invariante
del componente, no una ruta degradada de la página. Observación de redacción
(O-2), no de código.

---

## Salida de los comandos

Exit codes reales (comando ejecutado sin pipe, `$?` inmediato):

```
=== pnpm --filter web typecheck ===
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
EXIT=0

=== pnpm --filter web lint ===
$ eslint
EXIT=0

=== pnpm --filter web test ===
 RUN  v4.1.10 /home/enriquepaez/projects/backlogg/apps/web
 Test Files  130 passed (130)
      Tests  1193 passed (1193)
   Duration  44.82s (transform 10.84s, setup 108.33s, import 45.24s,
                     tests 88.66s, environment 180.89s)
EXIT=0

=== pnpm --filter web build ===
▲ Next.js 16.3.0 (Turbopack)
✓ Compiled successfully in 223ms
  Running TypeScript ...
  Finished TypeScript in 2.2s
✓ Generating static pages using 11 workers (69/69) in 1758ms
Route (app) ...
ƒ Proxy (Middleware)
EXIT=0
```

`bash init.sh` (protocolo del reviewer, backend):

```
........................................................ [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  SAWarning: New instance <Credit ...> conflicts with persistent instance ...
1499 passed, 1 warning in 67.02s (0:01:07)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

(El `SAWarning` y los avisos `metadataBase not set` / `Dynamic server usage`
del build son preexistentes en `main`.)

Recuento: `apps/web` pasa de 1186 a **1193** tests, 130 archivos. Backend
intacto en 1499.

---

## Observaciones no bloqueantes

- **O-1 — `AUTHOR` es copy que hoy no puede pintarse.** `CREDIT_ROLE_CODES`
  incluye `AUTHOR` y ambos `messages/*.json` llevan su etiqueta, pero solo
  movie/series montan la sección y `AUTHOR` solo existe para books
  (`docs/schema.md` l. 469-471). Por el mismo criterio que borró
  `DIRECTOR`/`CREATOR`, sobra. Dos salidas coherentes, a elección del leader:
  (a) dejar el vocabulario en `["ACTOR","WRITER","SOURCE_AUTHOR"]` y borrar la
  clave `AUTHOR` de los dos JSON — el test de exhaustividad ya existente lo
  protege; o (b) mantenerlo y sustituir la razón escrita en
  `credit-role-labels.ts:17-20` por la verdadera, dejando constancia en
  `docs/detail-page-layout.md` de que el vocabulario conserva `AUTHOR` a
  propósito. Hoy el doc dice «no llega» y el código le da etiqueta: no es una
  contradicción de comportamiento, pero sí de intención.
- **O-2 — Redacción en `progress/impl_FE-65.md`.** La decisión sobre
  `emptyMessage` («la clave sigue viva y usada», «ruta degradada ante
  `credits: undefined`») describe mal el motivo real, que es la obligatoriedad
  de la prop más la invariante propia del componente. Ver dictamen B. Es
  documentación, no código, pero conviene arreglarlo antes de que se cite como
  precedente.
- **O-3 — `item-credits.test.tsx` fija solo el copy en inglés.** El mapa
  `roleLabels` de las líneas 11-16 está hardcodeado en `en` a propósito (para
  fijar la etiqueta *renderizada*), así que ningún test de render prueba el
  español. Cubierto indirectamente por `credit-role-labels.test.ts:84-89`, que
  fija los strings de `es` contra el JSON. Suficiente; lo anoto solo porque la
  cadena «`es.json` → pantalla» no está cerrada por un único test.
- **O-4 — `credit-role-labels.ts` ya no solo tiene etiquetas.** Alberga
  `HERO_ROLES`, que es una decisión de layout, no de copy. La justificación
  (mantener juntas las dos mitades de la misma partición) es buena y la
  compro; solo queda el nombre del archivo un poco corto. Cosmético.
- **O-5 — `const heroRoles: readonly string[] = HERO_ROLES;`**
  (`page.tsx:358`). Ensanchamiento local del tuple `as const` para poder llamar
  a `.includes(credit.role)`. Es la solución barata y correcta; alternativa
  equivalente sería `(HERO_ROLES as readonly string[]).includes(...)`. Sin
  cambio recomendado.
- **O-6 — La rama sigue sin commits.** Todo el cambio está sin commitear, en
  línea con el flujo del proyecto (commit tras QA del leader y confirmación del
  usuario), pero conviene recordar que este veredicto describe el working tree
  del 2026-09-08 y deja de ser válido si el árbol se toca antes de commitear.
