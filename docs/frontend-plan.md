# Frontend — Plan de proyecto

> Estado: **planificación**. El backend inicial está completo (45/45 features, API bajo `/v1`).
> Este documento fija la arquitectura y el roadmap del frontend antes de escribir código.

## 1. Decisiones fijadas

| Decisión | Elección | Nota |
|----------|----------|------|
| Framework | **Next.js 15 (App Router) + React 19 + TypeScript** | SSR/ISR para catálogo público (SEO); islas cliente para lo interactivo |
| Auth | **BFF + cookie httpOnly** | Route Handlers de Next proxan a `/v1`; el navegador nunca ve tokens |
| UI | **Tailwind v4 + shadcn/ui** (Radix) | Accesible; tema claro/oscuro |
| Datos | **Cliente tipado generado de `/openapi.json`** + TanStack Query | Contrato siempre sincronizado con el backend |
| Scope v1 | **Paridad completa** con el backend (M0–M6) | Todo lo que expone la API |
| Repo | **Monorepo con workspaces** | Web y futura app nativa comparten `packages/` |
| Plataforma | **Camino A: Web + PWA ahora, nativa después** | PWA cubre "app" ya; nativa Expo futura reusa el core |
| i18n | **next-intl, bilingüe ES + EN** desde el scaffold | Segmento `app/[locale]/`; fallback `en` + detección por navegador. Traduce UI, no el contenido del catálogo |

## 2. Por qué "app-ready" sin tocar el backend

La API es **REST stateless con auth Bearer + refresh rotatorio**. Consecuencias:
- El **web** usa el patrón BFF: la cookie httpOnly guarda el refresh; Next orquesta la rotación server-side.
- Una **app nativa** futura se salta el BFF y habla `/v1` directo, guardando tokens en Keychain/Keystore.
- La **API con Bearer es la fuente de verdad**; el BFF es un adaptador solo-web encima. Ambos coexisten sin cambios de backend.

## 3. Estructura del monorepo

```
backlogg/
  backlogg/                 ← backend Python (existe)
  alembic/  docs/  tests/   ← backend (existe)
  apps/
    web/                    ← Next.js 15 (v1 del frontend)
    mobile/                 ← Expo/React Native (FUTURO, no ahora)
  packages/
    api-client/             ← tipos + cliente generados de /openapi.json  (web + nativo)
    core/                   ← lógica de dominio + esquemas zod             (web + nativo)
    config/                 ← tsconfig/eslint/prettier compartidos
```

- **Gestor**: pnpm workspaces. Node 20+.
- Web y (futuro) nativo comparten **la capa de contrato y validación**, no la UI.
- El harness actual (`init.sh`, pytest, ruff) es backend-only. El frontend necesitará su propio
  pipeline de verificación (typecheck + lint + test + build) y, si se orquesta con agentes,
  variantes frontend de implementer/reviewer. → **Item abierto (ver §9).**

## 4. Stack de librerías (apps/web)

| Área | Librería |
|------|----------|
| Data fetching cliente | TanStack Query v5 |
| Cliente API tipado | `openapi-typescript` (tipos) + `openapi-fetch` (fetch tipado) |
| Formularios | react-hook-form + zod + `@hookform/resolvers` |
| UI | Tailwind v4, shadcn/ui, Radix, lucide-react |
| Estado UI puntual | Zustand solo si hace falta (preferir server state + Query) |
| Testing | Vitest + Testing Library (unit), Playwright (e2e), MSW (mock de API) |
| Lint/format | ESLint (config Next) + Prettier |
| PWA | manifest + service worker (`@serwist/next` o `next-pwa`) |

## 5. Auth — flujo BFF

Route Handlers en `apps/web/app/api/auth/*` como proxy fino:

- `POST /api/auth/login` → llama `POST /v1/auth/login`; guarda `refresh_token` en cookie
  **httpOnly, Secure, SameSite=Lax**; mantiene el `access_token` server-side (cookie httpOnly corta
  o memoria de request); responde al cliente sin exponer tokens.
- `POST /api/auth/refresh` → usa el refresh de la cookie contra `POST /v1/auth/refresh`, **rota** y
  reescribe la cookie. Se dispara automáticamente cuando una llamada a `/v1` devuelve 401.
- `POST /api/auth/logout` → `POST /v1/auth/logout` + borra la cookie. Idempotente.
- **Server Components / Server Actions** usan un helper `apiFetch()` que adjunta el access token
  server-side y reintenta una vez tras refrescar ante 401.
- **middleware.ts** protege las rutas privadas (biblioteca, feed, listas, ajustes) redirigiendo a login.
- **Reuse detection**: si el refresh devuelve 401 (token robado/rotado), se limpia la sesión y se fuerza re-login.

**CORS**: al enrutar las llamadas a `/v1` **a través del servidor de Next** (BFF + Server Components),
el navegador habla same-origin con Next y Next habla server-to-server con la API → la superficie CORS
es mínima. Solo importaría si se hicieran llamadas directas navegador→`/v1` (se evita).

## 6. Rendering y datos

- **Catálogo público** (home, browse, detalle, search): **Server Components con ISR** (`revalidate`)
  para SEO y velocidad. Metadatos Open Graph por item (`generateMetadata`).
- **Superficies personales/sociales** (biblioteca, feed, listas, notificaciones, recomendaciones):
  cliente con **TanStack Query** a través del BFF; optimistic updates donde aporte.
- **Imágenes**: `next/image` con `remotePatterns` para los hosts de posters (TMDB, Open Library, IGDB).
- **Paginación**: `page/limit` (espejo del backend). **Rate limit**: manejar `429 + Retry-After`
  (auth y search fallback) con UX de reintento.

## 7. Roadmap por milestones (backlog frontend)

Identificadores `FE-n`. Dependencias entre milestones son secuenciales salvo nota.

### M0 — Fundaciones
- **FE-1** Scaffold monorepo (pnpm workspaces, `apps/web` Next 15 TS, `packages/{api-client,core,config}`, tsconfig/eslint/prettier compartidos).
- **FE-2** Generación del cliente API (`openapi-typescript` + `openapi-fetch` desde `/openapi.json`; script de regeneración; `packages/api-client`).
- **FE-3** Design system base (Tailwind v4 + shadcn/ui init; tokens de tema claro/oscuro; layout raíz, header/nav/footer, tipografía).
- **FE-3b** i18n con next-intl (segmento `app/[locale]/`, middleware de locale, catálogos `es`/`en`, fallback `en` + detección; helpers de traducción server+client). Claves de mensaje desde el día 1 (nada de strings hardcodeados).
- **FE-4** Fundación auth BFF (Route Handlers login/refresh/logout; cookie httpOnly; helper `apiFetch` con auto-refresh; `middleware.ts` de rutas privadas).
- **FE-5** App shell y convenciones (loading/error/not-found, toasts, QueryClient provider, config de entorno).
- **FE-6** PWA base (manifest, iconos, service worker, instalable).
- **FE-7** Testing + CI frontend (Vitest, Playwright, MSW; job de CI: typecheck + lint + test + build).

### M1 — Catálogo público (SEO)
- **FE-8** Home/landing (trending + destacados por tipo).
- **FE-9** Browse por tipo ×4 (filtro por género, sort, paginación) — SSR/ISR.
- **FE-10** Detalle de item (poster, metadatos, `rating_internal`/`rating_external`, credits, similar, hueco de `viewer_status`) — SSR/ISR + OG metadata.
- **FE-11** Búsqueda global (filtro por tipo, paginación, manejo de 429).
- **FE-12** Browse de géneros y trending.

### M2 — Auth y cuenta
- **FE-13** Registro + login (rhf+zod; 409/422/429).
- **FE-14** UX de sesión (estado auth, menú de cuenta, logout, ciclo de refresh e2e).
- **FE-15** Verificación de email (ruta `/verify-email` → `POST /v1/auth/verify/confirm`).
- **FE-16** Recuperación de password (ruta `/reset-password` → `forgot`/`reset`).
- **FE-17** Ajustes de cuenta (editar perfil `PATCH /v1/users/me`, pedir verificación, **borrar cuenta**).

### M3 — Personal
- **FE-18** Puntuar y reseñar (widget de rating + compositor de review en detalle; `PUT/DELETE rating`; botón **reportar**).
- **FE-19** Listado de reviews por item (con like/unlike).
- **FE-20** Biblioteca/backlog (cambiar estado en detalle; `viewer_status`; página de biblioteca con filtros y counts).
- **FE-21** Perfil público de usuario (`/u/{username}`: reviews, biblioteca, counts de followers/following, listas).

### M4 — Social
- **FE-22** Follows (botón follow/unfollow, listas de followers/following).
- **FE-23** Feed de actividad (pestañas following/popular, paginación).
- **FE-24** Notificaciones (campana + badge `unread_count`, lista, marcar leídas).

### M5 — Listas y recomendaciones
- **FE-25** CRUD de listas (crear/editar/borrar, pública/privada).
- **FE-26** Items de lista (añadir/quitar, reordenar drag-and-drop, página pública de lista).
- **FE-27** Recomendaciones (filtro por tipo, motivos legibles).

### M6 — Admin de moderación (gated, opcional)
- **FE-28** Auth admin (X-API-Key **solo server-side** en el BFF; sección admin protegida).
- **FE-29** Cola de reportes (listar, filtrar por estado, resolver).
- **FE-30** Acciones de moderación (hide/unhide review, ban/unban usuario).

## 8. Wiring de entorno / despliegue

- **Backend**: `APP_BASE_URL` debe apuntar al **origen del web** (los enlaces de email resuelven a
  `/verify-email` y `/reset-password`). `CORS_ORIGINS` con el origen del web (mínimo por el BFF).
- **Web (Next)**: `API_INTERNAL_URL` (servidor→`/v1`; en dev `http://localhost:8000`). Cookies
  `Secure` en prod. Sin secretos de API en el bundle cliente (todo sensible vive en el BFF).
- **Despliegue web**: Vercel (DX/ISR nativos para Next) o Render junto al backend. → decisión no bloqueante.

## 9. Items abiertos / riesgos

- **Harness de agentes**: implementer/reviewer y `init.sh` son backend-Python. Si el frontend se
  orquesta con agentes, hay que crear variantes frontend (verificación = typecheck + lint + test + build)
  y decidir si el backlog frontend va en un `frontend_feature_list.json` separado (recomendado, para no
  mezclar con el backend Python).
- **ISR**: estrategia de revalidación del catálogo (tiempo fijo vs on-demand cuando el sync nocturno actualiza).
- **PWA Web Push**: en iOS solo con PWA instalada (16.4+). Gestionar expectativas; nativo lo resuelve mejor a futuro.
- **Despliegue**: elegir Vercel vs Render para el web.

## 10. Siguiente paso

Arrancar **M0 (FE-1 → FE-7)**: scaffold del monorepo, cliente tipado, design system, fundación auth BFF,
app shell, PWA base y CI. Al terminar M0 hay base sólida para construir el catálogo público (M1).
