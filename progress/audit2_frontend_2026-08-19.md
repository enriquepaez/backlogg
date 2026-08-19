# Audit 2 — Frontend (2026-08-19)

Auditoría de seguimiento a `progress/audit_ux_2026-08-18.md`: (1) verificación
de las 9 features propuestas en ese audit (ahora `FE-36`..`FE-44` en
`frontend_feature_list.json` — nótese que el encargo original las llamaba
"FE-35 a FE-43", pero los códigos reales asignados por el leader son
`FE-36..FE-44`; `FE-35` es `browse_search_filters`, una feature distinta no
incluida en este batch), y (2) un pase fresco de production-readiness sobre
`apps/web`, estático (sin navegador — un agente separado cubre el walkthrough
en vivo con Playwright en paralelo).

**Método**: lectura de cada componente/página implicado en `apps/web/src`,
comparado línea a línea contra el campo `acceptance` de cada feature en
`frontend_feature_list.json`. Además, verificación ejecutable real (no solo
lectura): `npm run typecheck`, `npm run lint` y `npm run test -- --run`
corridos contra el árbol actual — los tres en verde (typecheck sin errores,
0 problemas de lint, 119 archivos de test / 1041 tests en verde), lo que
respalda directamente el criterio de aceptación común a las 9 features
("typecheck+lint+build en verde").

## Verificación features FE-36 a FE-44

### FE-36 — library_nav_entry: **cumple**
- Header: `src/components/site-header.tsx:71-77` añade el enlace a
  `/u/{username}/library` dentro del `<nav>`, en la misma posición/estilo que
  `Feed`/`For you`, envuelto en el mismo `navUser ?` gate que esos dos
  (`site-header.tsx:55-79`) — no aparece sin sesión.
- Dropdown de cuenta: `src/components/user-nav.tsx:103-108` añade la misma
  entrada con icono `Library`.
- i18n: clave `Nav.library` presente en `messages/en.json:866` y
  `messages/es.json:866` ("Library"/"Biblioteca"), sin strings hardcodeados.
- Verificado ejecutable: typecheck/lint/test en verde (ver método arriba).

### FE-37 — library_status_colors: **cumple**
- 4 tokens nuevos en `src/app/globals.css:189-196` (light) y `:260-267`
  (dark) — `--status-want/in-progress/completed/dropped` (+`-foreground`).
  Comentario extenso (`globals.css:126-188`) documenta el proceso de
  selección de hue/lightness/chroma y los ratios de contraste WCAG
  calculados a mano (OKLCH -> OKLab -> LMS -> sRGB lineal), no solo
  "a ojo": 7 de 8 pares AAA (>=7:1), el octavo (`--status-dropped` dark)
  AA (4.99:1) con justificación explícita de por qué no se pudo subir más
  sin colisionar visualmente con `--destructive`.
- Selector de estado del item detail: `viewer-status-slot.tsx:171-192` usa
  `STATUS_COLOR_CLASSES_IMPORTANT` (variante con `!important`, ver el
  comentario en `src/lib/library-types.ts:184-212` que documenta un bugfix
  real post-QA: el `variant="outline"` de shadcn Button perdía la carrera de
  especificidad contra el color de estado en tema oscuro).
- Tabs de biblioteca: `StatusTabs` en
  `src/app/[locale]/u/[username]/library/page.tsx:139` usa
  `STATUS_COLOR_CLASSES[tab.value]` en el tab activo.
- Badge en `CatalogCard`: `src/components/catalog-card.tsx:105-114`, solo
  cuando `libraryStatus`+`libraryStatusLabel` están presentes — acotado
  correctamente a la única grid que hoy trae `viewer_status` por item
  (`/u/[username]/library`), tal como el acceptance permite explícitamente
  ("en grids sin viewer_status por item, el badge se omite en esta
  iteración").
- Centralización: `STATUS_COLOR_CLASSES` en `src/lib/library-types.ts:175-181`
  es la única fuente de verdad, reutilizada también por `LibraryBoard`
  (`library-board.tsx:73`) y `LibraryStatusCounts`
  (`library-status-counts.tsx:45`) — más allá de los 3 sitios mínimos que
  pedía el acceptance.
- Badge no depende solo del color: siempre va acompañado de texto
  (`libraryStatusLabel`), por lo que no es un problema de accesibilidad para
  usuarios con daltonismo.

### FE-38 — library_sort: **cumple**
- `src/components/library-sort.tsx`: `<select>` con las 4 opciones
  (`updated_desc` default, `rating_desc`, `title_asc`, `date_desc`),
  navega vía `router.replace` a `?sort=`.
- Query string compartible/recargable: `page.tsx:72-75` (`parseSort`) lee
  `searchParams.sort` en cada render server-side.
- Combinable con filtros existentes: `LibrarySortSelect` recibe y preserva
  `status`/`type` en su propio `navigate` (`library-sort.tsx:50-61`), y
  `StatusTabs`/`TypeTabs` preservan `sort` en sus propios `hrefFor`
  (`page.tsx:115`, `:174`).
- i18n: namespace `Library.sort` presente en ambos locales.

### FE-39 — library_counts_profile: **cumple**
- `src/components/library-status-counts.tsx`: 4 conteos en
  `grid-cols-2 sm:grid-cols-4`, colores de `STATUS_COLOR_CLASSES` (FE-37),
  cada uno un `Link` a `/u/{username}/library?status={status}`.
  `counts[status]` viene de `UserOut.library_counts`, público — se renderiza
  igual en perfil propio y ajeno (no hay gate de `isOwnLibrary`).
- Nota de seguimiento ya documentada en el audit original (QA manual
  2026-08-18): el resumen prominente no "viaja" a la propia página de
  biblioteca (`/u/[username]/library` sigue mostrando solo los números
  pequeños de `StatusTabs`) — aceptado explícitamente como fuera de scope de
  FE-39 en su momento; sigue así hoy. No es una regresión, es scope conocido.

### FE-40 — design_system_accent_pass: **cumple**
- Token `--accent` con croma real: `globals.css:116-118` (light,
  H 292 violeta) y `:227-229` (dark). `--accent-hover` como token explícito
  separado (no un simple `/80` de opacidad). `--primary`/`--ring` aliasan
  `--accent` (`globals.css:119-120`, `:199`, `:230-231`, `:270`), por lo que
  botones primarios, enlaces y foco lo heredan sin overrides ad-hoc.
- Tipografía de titulares: `src/app/[locale]/layout.tsx:28-33` — `Space
  Grotesk` vía `next/font/google` con `variable: "--font-heading"`,
  self-hosted en build (sin dependencia de una CDN bloqueable por CSP, según
  el propio comentario del código). `--font-heading` ya no es alias de
  `--font-sans`.
- Contraste verificado y documentado con números reales: light
  ~6.92:1/8.78:1, dark ~7.65:1/9.63:1 (`globals.css:106-114`).
- Sin overrides ad-hoc: `grep` de colores hardcodeados (`bg-blue-*`,
  hex literales, etc.) en `src/components/ui/*.tsx` no encontró nada.

### FE-41 — activity_log_ui: **cumple**
- Control de registro: `src/components/activity-log-widget.tsx:212-258`,
  formulario con fecha (`max` acotado a hoy), checkbox rewatch, nota — llama
  a `POST /api/{type}/{slug}/log` (`:121-129`).
- Historial propio con borrado por entrada: `:260-276`
  (`LogEntryCard` + `handleDelete`, `:159-189`).
- Independiente del rating widget: ambos widgets se montan por separado en
  la página de item detail y no comparten estado (confirmado por el propio
  comentario del archivo, `:48-52`); ninguno de los dos requiere que el otro
  tenga datos.
- Estados de carga/error/vacío/anónimo cubiertos explícitamente: `phase`
  distingue `loading`/`anonymous`/`load-error`/`ready`
  (`activity-log-widget.tsx:197-209`), e historial vacío tiene su propio
  copy (`t("historyEmpty")`, `:263`).
- Nota de contenido de usuario: la nota (`entry.note`) se renderiza como
  texto React puro con `whitespace-pre-wrap` (`:306`), nunca vía
  `dangerouslySetInnerHTML` — sin vector XSS.

### FE-42 — feed_notifications_richer_ui: **cumple**
- `feed-entry-list.tsx`: rama `status_completed` (`entry.event_type ===
  "status_completed"`, `:81`) renderiza autor+item+fecha con
  `FeedEntryCompletedBadge` (`:190-202`, mismo `STATUS_COLOR_CLASSES.completed`
  de FE-37) en vez de estrellas/texto — el `rating_created` existente sigue
  intacto en la misma rama condicional (`:119-124`).
- `notification-bell.tsx`: `notificationMessage` (`:217-229`) tiene rama
  explícita para `user_completed` (copy propio, `t("userCompleted")`) además
  del genérico `t("generic")` de fallback; icono propio superpuesto al
  avatar del actor (`:262-280`, mismo `CheckCircle2`+color que el badge del
  feed, para consistencia visual entre ambas superficies).
- i18n: claves `Feed.entry.completedBadge`/`completedDateLabel` y
  `Notifications.userCompleted` presentes en ambos locales.

### FE-43 — library_board_view: **cumple**
- Toggle grid/board: `src/components/library-view-toggle.tsx`, renderizado
  por `page.tsx:344-353` **solo** cuando `isOwnLibrary` (`:319`) — en
  perfiles ajenos `view` se fuerza a `"grid"` sin importar el `?view=` de la
  URL (`page.tsx:320`), cumpliendo "en perfiles ajenos se mantiene solo la
  grid, de solo lectura".
- 4 columnas con color+conteo: `library-board.tsx:69-78`, header con
  `STATUS_COLOR_CLASSES[status]` y `countsByStatus[status]`.
- Sin drag-and-drop: confirmado, cada `LibraryBoardCard` es un enlace simple
  a `/{type}/{slug}` (`library-board-card.tsx:45-51`), no hay ningún
  handler de drag en el board.
- Persistencia en localStorage: `library-view-toggle.tsx:30-32`
  (`storageKeyFor`, clave por username) + efecto de redirect-on-mount
  (`:83-95`) cuando no hay `?view=` explícito en la URL.
- Responsive: `library-board.tsx:64` usa
  `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4` — las columnas se apilan en
  mobile (no scroll horizontal), consistente con el resto de grids del
  código (comentario `:54-58` documenta la decisión explícitamente).

### FE-44 — rating_widget_half_star: **cumple**
- `rating-widget.tsx`: `StarPicker` (`:436-491`) parte cada estrella en dos
  botones reales (mitad izq/der), seleccionando pasos de 0.5 de 1.0 a 5.0;
  la primera estrella correctamente omite su mitad izquierda (equivaldría a
  0.5, por debajo del mínimo `ge=1` del backend, `:454-456`).
  Cada mitad es un `<button>` propio con `aria-label`/`aria-pressed`
  independiente → navegable y operable por teclado (Tab + Enter/Espacio),
  sin necesidad de manejo de flechas.
- Lectura consistente: `src/components/star-rating.tsx` (`StarRating`,
  `StarIcon`, `starFillAt`) es el único renderer compartido por
  `rating-widget.tsx` (resumen), `item-reviews.tsx:269`,
  `user-review-card.tsx:63`/`:79` y `feed-entry-list.tsx` — los 4 sitios que
  pedía el acceptance renderizan medias estrellas de forma idéntica.
- Sin regresión en ratings enteros: `starFillAt` (`star-rating.tsx:51-57`)
  trata un score entero como caso particular del mismo cálculo (sin rama
  especial), y el propio código documenta un bugfix post-QA real (`size-full`
  vs tamaño explícito en `HalfStar`, `:91-113`) capturado con una captura
  Chromium real, no solo jsdom.
- Persistencia tras recargar: el flujo `PUT` guarda `score` (incluyendo
  `.5`) contra el backend real (`handleSubmit`, `:148-191`) y el
  `GET` inicial (`:98-127`) recarga ese mismo valor — nada en el cliente
  redondea o trunca el score en ningún punto del pipeline.
- Extra (no pedido explícitamente pero relevante para producción): fix de
  usabilidad post-lanzamiento documentado en el propio código
  (`rating-widget.tsx:410-434`) — objetivo de click ampliado de 12px a 18px
  por mitad (WCAG 2.5.5) y preview en vivo al hover/focus antes de
  confirmar la selección.

**Resumen**: las 9 features cumplen genuinamente sus criterios de
aceptación, con evidencia verificable en código — no solo el flag `done`.
Nivel de documentación inline inusualmente alto (comentarios que explican
decisiones de contraste, bugfixes post-QA reales con root cause, y
trade-offs de scope explícitos). typecheck/lint/test corridos de verdad en
esta sesión, los tres en verde.

## Nuevos hallazgos (production readiness / polish)

### Alto

1. **Los perfiles públicos `/u/{username}` y `/u/{username}/library` no
   tienen `generateMetadata`** — `src/app/[locale]/u/[username]/page.tsx` y
   `src/app/[locale]/u/[username]/library/page.tsx` no exportan
   `generateMetadata` en absoluto (confirmado con `grep -c generateMetadata`
   → 0 en ambos), a diferencia de `[type]/[slug]/page.tsx:162` que sí lo
   tiene. Cada perfil de usuario — la superficie pública más "shareable" del
   producto (comparable a un perfil de Letterboxd) — sirve el `<title>`/
   descripción genéricos del layout raíz en vez de "Nombre — Backlogg", y no
   tiene Open Graph propio, así que un link a un perfil compartido en redes
   se ve genérico. **Fix sugerido**: añadir `generateMetadata` a ambas
   páginas, siguiendo el mismo patrón que `[type]/[slug]/page.tsx` (título
   con `display_name`/`username`, OG image con el avatar si existe).

2. **No hay `sitemap.ts` ni `robots.ts`** en `src/app/` (`find` no encontró
   ninguno). Para un producto cuyo catálogo público (`/movie/*`, `/series/*`,
   `/book/*`, `/game/*`, `/u/*`) está pensado para SEO (`docs/frontend-plan.md`
   §6: "Catálogo público ... SSR con ISR para SEO"), lanzar a producción sin
   sitemap deja todo el descubrimiento por crawler a enlaces internos
   únicamente. **Fix sugerido**: `src/app/sitemap.ts` con al menos las rutas
   de catálogo público paginadas desde la API, y un `robots.ts` básico.

### Medio

3. **Las estrellas de solo-lectura son invisibles para lectores de
   pantalla** — `src/components/star-rating.tsx:32-40` (`StarRating`) no
   tiene `aria-label`/`role` en el `<div>` contenedor, y cada `<Star>` que
   renderiza es `aria-hidden` (`star-rating.tsx:78,83`, y `HalfStar` en
   `:122,124`). Los 4 call sites que muestran una puntuación guardada
   (`rating-widget.tsx:251` resumen, `item-reviews.tsx:269`,
   `user-review-card.tsx:63`, `feed-entry-list.tsx` vía `StarRating`) no
   tienen ningún texto equivalente cerca — quien usa un lector de pantalla
   no se entera de qué puntuación tiene una review, en ningún sitio de la
   app. Esto no es nuevo de FE-44 (ya existía antes), pero FE-44 tocó
   exactamente este archivo y no lo corrigió. **Fix sugerido**: añadir
   `aria-label={t("scoreAriaLabel", { value: score })}` (o similar) al
   `<div>` de `StarRating`, con un fallback tipo "sin puntuación" cuando
   `score` es `null`.

4. **Los widgets "personales" (rating, library status, activity log,
   notificaciones) no usan TanStack Query, pese a que el proyecto lo tiene
   configurado y documentado como el patrón obligatorio** —
   `docs/frontend-plan.md` §6 dice explícitamente: "Superficies
   personales/sociales ... cliente con TanStack Query a través del BFF;
   optimistic updates donde aporte." `src/components/query-provider.tsx`
   monta un `QueryClientProvider` real en el layout raíz, pero
   `grep -rl "useQuery\|useMutation"` sobre `src/` (excluyendo tests) no
   encuentra ningún uso. En su lugar, `rating-widget.tsx`,
   `viewer-status-slot.tsx`, `activity-log-widget.tsx` y
   `notification-bell.tsx` reimplementan cada uno, por separado, el mismo
   patrón `useState<Phase>` + `useEffect` + `fetch` + rollback manual en
   error — con las mismas 4-5 fases (`loading`/`anonymous`/`load-error`/
   `ready`) casi copiadas literalmente entre archivos. No es un bug
   funcional (cada copia está bien hecha, con tests), pero es deuda técnica
   real: cuatro implementaciones divergentes del mismo problema, sin caché
   entre navegaciones, sin invalidación cruzada (p.ej. cambiar el estado de
   biblioteca en el item detail no invalida el `library_counts` ya
   renderizado en el perfil si se navega hacia atrás) y contradice la
   arquitectura documentada por el propio proyecto. **Fix sugerido**: no es
   bloqueante para shipear, pero vale la pena abrir una feature de
   refactor dedicada antes de que se sumen más widgets con este mismo
   patrón duplicado.

### Bajo

5. **Avatares de usuario nunca pasan por `next/image`** —
   `next.config.ts:20-27` solo registra `remotePatterns` para los 3 hosts de
   pósters de catálogo (TMDB/Open Library/IGDB); ningún host de avatar está
   configurado. Como consecuencia, cada avatar en la app (`user-nav.tsx:78`,
   `feed-entry-list.tsx:162`, `notification-bell.tsx:253`,
   `rating-widget.tsx:374`) usa un `<img>` plano sin optimizar, sin
   `sizes`/lazy-loading automático. Cada sitio lo documenta como decisión
   consciente ("Avatar hosts aren't configured in next/image's
   remotePatterns yet"), así que es deuda conocida, no un descuido — pero al
   ser 4+ sitios repitiendo el mismo comentario, ya justifica resolverlo de
   una vez en vez de seguir pateándolo feature a feature. **Fix sugerido**:
   si los avatares vienen de un host fijo/propio (ver FE-31 avatar_upload),
   añadirlo a `remotePatterns` y migrar los 4 sitios a `next/image` en un
   solo cambio.

6. **`ActivityLogWidget` no pide confirmación antes de borrar una entrada de
   log** — `activity-log-widget.tsx:309` (`onClick={onDelete}` directo,
   sin diálogo intermedio), a diferencia de `delete-account-dialog.tsx` que
   sí usa un diálogo de confirmación para una acción destructiva análoga.
   Menor porque una entrada de log es de bajo impacto (a diferencia de
   borrar la cuenta), pero es inconsistente con el patrón de confirmación ya
   establecido en el propio código para acciones "destructive". No bloqueante.

No se han vuelto a proponer listas curadas ni ninguna otra funcionalidad ya
descartada explícitamente por el usuario (ver `progress/audit_ux_2026-08-18.md`).
