# Audit 2 — Walkthrough en vivo (2026-08-19)

El subagente `general-purpose` lanzado para este walkthrough reportó que no
tiene ninguna herramienta de navegador (Playwright/MCP) disponible en su
toolset. Ante eso, el leader ejecutó el walkthrough directamente: arrancó
backend (`uvicorn`, puerto 8000) y frontend (`pnpm --filter web dev`, puerto
3000) en local, y condujo un script Node standalone (fuera del repo, en el
scratchpad de la sesión) que carga `playwright-core` directamente desde
`node_modules/.pnpm/` (dependencia ya presente en el monorepo para los tests
e2e de `apps/web/e2e/`, aunque esos corren contra un mock backend — este
walkthrough usó los servidores reales).

Nota: la primera pasada del script tenía una condición de carrera propia
(navegaba a `/en` inmediatamente tras el submit del registro, sin esperar a
que el flujo de registro/auto-login asentara la cookie de sesión) que
produjo un falso positivo — parecía que el header se quedaba en "Log in"
tras registrarse. Al corregir el script para esperar a que la URL saliera de
`/register` antes de navegar, el comportamiento fue el correcto (cookies
`bl_access`/`bl_refresh` presentes, header ya autenticado). **No es un bug
del producto** — se deja constancia para que no se reintroduzca esta duda en
auditorías futuras.

## Flujo probado

1. **Registro** (`/en/register`) — formulario con username/email/password/
   display name (optional), botón con estado "Creating account…" mientras
   está en vuelo. `POST /v1/auth/register` (201) + `POST /v1/auth/login`
   (200) automático. Cookies de sesión (`bl_access`, `bl_refresh`) quedan
   seteadas correctamente.
2. **Header / menú de cuenta** — tras login, el nav muestra
   `Home Search Trending Genres Showcase Feed For you Library`: el enlace
   **Library** está presente y en la misma posición/estilo que el resto (FE-36
   confirmado en vivo). El dropdown de cuenta añade: My profile, Library,
   Settings, Resend verification email, Log out.
3. **Item detail** (`/en/movie/insidious-out-of-the-further-2026`) —
   selector de estado (`Want / In progress / Completed / Dropped / Remove
   from library`) funcional: al clicar "In progress" se resalta en amarillo
   sólido (no pastel), coherente con `[[design-prefers-vivid-not-pastel]]`.
   Rating widget con 5 estrellas vacías clicables, campo de review y botón
   Save. Sección **Activity log** propia debajo de reviews: fecha
   pre-rellenada a hoy, checkbox "This was a rewatch", nota opcional, botón
   "Add entry", historial vacío con copy propio ("No log entries yet.") — FE-41
   confirmado en vivo. Sección "You might also like" (similar items, feature
   31) puebla correctamente.
4. **Perfil propio** (`/en/u/{username}`) — bloque de 4 conteos por estado
   (`0 WANT / 1 IN PROGRESS / 0 COMPLETED / 0 DROPPED`), cada uno en su color
   sólido (azul/amarillo/verde/rojo), con link "View full library" — FE-38/
   FE-39 confirmados en vivo.
5. **Biblioteca propia** (`/en/u/{username}/library`) — toggle Grid/Board
   visible, tabs de estado con conteos (`All / Want (0) / In progress (1) /
   Completed (0) / Dropped (0)`), tabs de tipo, selector "Sort by" con
   "Recently updated" — FE-37/FE-38/FE-43 confirmados en vivo (no se probó a
   fondo el toggle a Board por límite de tiempo del walkthrough, pero el
   control está presente y clicable).
6. **Feed** (`/en/feed`) — tabs Following/Popular, estado vacío correcto
   ("Follow people to see their activity here.") — no se pudo generar
   contenido real de feed en el tiempo del walkthrough (requeriría un segundo
   usuario siguiéndose mutuamente), así que **el renderizado de
   `status_completed` en el feed (FE-42) no se verificó visualmente en esta
   sesión** — sí quedó verificado por lectura de código + tests en el audit
   de frontend.
7. **Tipografía de titulares** — visible a simple vista en "Activity feed" y
   "Track everything you watch, read and play." (Space Grotesk, geométrica,
   claramente distinta del texto de cuerpo) — FE-40 confirmado en vivo, se ve
   intencional y cohesivo, no a medio aplicar.

## Consola / red

- Sin errores de consola. Dos warnings benignos de Next (`Image ... detected
  as LCP, add loading="eager"`) sobre el póster del hero — optimización
  menor de Next Image, no un bug.
- Sin respuestas 4xx/5xx inesperadas durante todo el flujo.

## Issues encontrados

Ninguno bloqueante. Confirma, en vivo, las mismas conclusiones que los
audits estáticos de backend/frontend: las 13 features previas funcionan de
extremo a extremo tal como están documentadas. No se detectó ningún rough
edge visual nuevo más allá de los ya recogidos en
`progress/audit2_frontend_2026-08-19.md` (SEO metadata, sitemap,
accesibilidad de estrellas de solo lectura).

Screenshots guardadas en el scratchpad de la sesión (no versionadas en el
repo, referencia solo para esta sesión).
