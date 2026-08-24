# Audit frontend #3 — verificación de FE-45..FE-50 + production readiness ampliado

Fecha: 2026-08-24. Auditoría de solo lectura (`apps/web/src` no modificado).
Sigue a `progress/audit2_frontend_2026-08-19.md`, que propuso las features
FE-45..FE-50, ya marcadas `done` en `frontend_feature_list.json`.

Método: lectura línea a línea de cada archivo implicado, comparado contra el
`acceptance` de cada feature, más ejecución real de la pipeline: `npm run
typecheck` (verde), `npm run lint` (verde, 0 problemas), `npm run test -- --run`
(verde, **122 archivos / 1059 tests**). Pase de production-readiness
deliberadamente más amplio que el de audit2 (que se centró en SEO/metadata/
sitemap/a11y de estrellas/TanStack Query/avatares/confirm-dialog): a11y más
allá de las estrellas, responsive, performance, estados de error/loading,
SEO estructural, i18n, manejo de sesión expirada y deuda técnica.

---

## Verificación FE-45 a FE-50

Las 6 features cumplen genuinamente su `acceptance`, con evidencia
verificable en código — no solo el flag `done`:

- **FE-45 profile_seo_metadata** — `generateMetadata` en `u/[username]/page.tsx:58-83`
  y `u/[username]/library/page.tsx:255-280`, título con `display_name`/
  `username`, OG con avatar y fallback genérico.
- **FE-46 sitemap_robots** — `src/app/sitemap.ts` pagina catálogo público con
  salvaguardas (`MAX_PAGES_PER_TYPE`), `hreflang` por locale; `robots.ts`
  excluye rutas privadas y referencia el sitemap. Deliberadamente sin `/u/*`
  (no hay endpoint para listar usernames), documentado inline.
- **FE-47 rating_accessibility_labels** — `star-rating.tsx:58-69` con
  `role="img"` + `aria-label`, heredado sin cambios propios por los 4 call
  sites que pedía el acceptance.
- **FE-48 personal_widgets_query_refactor** — los 4 widgets usan `useQuery`/
  `useMutation` (cero `useState+useEffect+fetch` manual residual), con
  invalidación cruzada real verificada (`viewer-status-slot.tsx:197/223`
  invalida `library.counts` tras cada mutación).
- **FE-49 avatar_next_image** — cumple para los 4 sitios pedidos
  explícitamente por el acceptance original. Quedan 4-5 sitios adicionales
  sin migrar (ver hallazgo MEDIUM #1 abajo) — no es un incumplimiento de
  FE-49, cuyo scope estaba acotado a esos 4 sitios.
- **FE-50 activity_log_delete_confirm** — `LogEntryCard` envuelve el
  borrado en un `Dialog`, mismo patrón que `delete-account-dialog.tsx`.

Sin stubs ni regresiones detectadas.

---

## Nuevos hallazgos (production readiness)

### Alto

Ninguno que bloquee producción.

### Medio

1. **FE-49 dejó 4-5 sitios de avatar sin migrar a `next/image`, con
   comentarios inline que ya no son ciertos** — `u/[username]/page.tsx`
   (hero de perfil), `admin/users/[username]/page.tsx`,
   `follow-user-list.tsx` e `item-reviews.tsx` (`ReviewAuthor`) siguen con
   `<img>` plano pese a que `remotePatterns` para avatares ya está
   configurado; cada comentario cita como rationale un sitio que ya SÍ está
   migrado, formando una cadena de referencias obsoletas. `avatar-upload-field.tsx`
   es un caso parcialmente distinto (preview local vía `blob:` URL, que
   `next/image` no puede optimizar igual). → **frontend feature FE-51**
   (`avatar_next_image_remaining_sites`, pending).

2. **Sin `loading.tsx` para `/search`, `/feed`, `/u/[username]` ni
   `/admin/*`**, a diferencia de `browse/[type]`, `genres`,
   `recommendations`, `trending` y `[type]/[slug]` que sí lo tienen. Las 5
   rutas afectadas son Server Components `async` con fetch a la API —
   durante la resolución no hay feedback visual más allá del indicador
   nativo del navegador. Search y feed son rutas de alto tráfico. →
   **frontend feature FE-52** (`loading_states_remaining_routes`, pending).

3. **Sin canonical tags ni JSON-LD (structured data) en ningún sitio de la
   app** — `sitemap.ts` (FE-46) genera `alternates.languages` a nivel de
   sitemap, pero ninguna página exporta `alternates.canonical`; rutas con
   query params (`browse/{type}?genre=...`, `search?q=...`) quedan
   indexables como URLs distintas sin canónica declarada. Sin JSON-LD
   (`Movie`/`TVSeries`/`Book`/`VideoGame`) en el detalle de item, el
   catálogo pierde rich snippets pese a estar explícitamente diseñado para
   SEO (`docs/frontend-plan.md` §6). → **frontend feature FE-53**
   (`seo_canonical_structured_data`, pending).

4. **Manejo de 401 inconsistente entre los 4 widgets migrados a TanStack
   Query (FE-48)** — `rating-widget.tsx` y `activity-log-widget.tsx`
   distinguen explícitamente un 401 ("tu sesión expiró") de otros errores,
   pero `viewer-status-slot.tsx` y `notification-bell.tsx` solo distinguen
   éxito de "failed" genérico — un 401 real cae en el mismo toast que un
   fallo de red o un 500. No es una regresión de FE-48 (el comportamiento
   pre-refactor tampoco lo distinguía en esos 2 archivos), pero la
   migración fue la oportunidad natural de unificarlo. → **frontend
   feature FE-54** (`widget_401_handling_consistency`, pending).

### Bajo

5. **`LogoutButton` es código muerto** — no está montado en ningún sitio
   (`UserNav` renderiza su propio `DropdownMenuItem`), documentado como
   decisión deliberada en su propio doc comment ("kept as a reusable
   primitive for future surfaces"). Deuda genuina pero trivial de resolver
   (borrar archivo + test) si nadie lo termina usando; no se convierte en
   feature formal.

6. **`SITE_URL` cae a `http://localhost:3000` por defecto si la env var no
   está seteada** — usado tanto por `sitemap.ts`/`robots.ts` como por
   `metadataBase` del layout raíz. Si no se configura en producción, el
   sitemap y el Open Graph generarían URLs `localhost`, sin warning en
   build. No es un bug de código — verificar como parte del checklist de
   despliegue, no como feature.

---

## Verificado sin hallazgos ("revisado, sin hallazgos")

- **Foco/teclado en modales y dropdowns**: todos los overlays están
  construidos sobre primitivos Radix, que ya implementan focus trap,
  `Escape` y roles ARIA correctos.
- **Landmarks/ARIA**: `<header>`, `<nav aria-label>`, `<main>`, `<footer>`
  presentes y semánticamente correctos.
- **Responsive de tablas admin y board view**: `overflow-x-auto` en el
  primitivo de tabla; board view se apila en mobile sin scroll horizontal
  roto. Sin anchos fijos en px que rompan mobile en toda la app.
- **i18n**: sin strings hardcodeadas fuera de `showcase/page.tsx` (kitchen-
  sink interno, ya excluido de `robots.ts`/`sitemap.ts`).
- **`use client` innecesario**: no se encontró ningún caso claro de Server
  Component convertido innecesariamente a Client Component.
- **Lazy loading / bundle size**: sin librerías pesadas que justifiquen
  `next/dynamic`; el App Router ya divide por ruta.
- **Dead code / duplicación** más allá de `LogoutButton`: la duplicación
  entre componentes similares (p. ej. `ReviewAuthor` repetido) está
  documentada como decisión de estilo deliberada, no deuda accidental.
- **Consistencia con `docs/frontend-plan.md`**: TanStack Query, next/image
  con remotePatterns, BFF + cookie httpOnly, SSR/ISR, i18n bilingüe — todo
  consistente con lo documentado.
