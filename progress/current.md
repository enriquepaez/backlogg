# Sesión actual

## Backend inicial — COMPLETO y en `main`

45/45 features `done`, API bajo `/v1`. Nota: los PRs #70/#71/#72 (apilados con base en la rama
padre) se mergearon entre sí en vez de a `main`; se consolidaron con el **PR #73**
(`feat/api_versioning` → `main`, ya mergeado). `main` tiene todo: `/v1`, migraciones 0017/0018,
módulos reports + moderation.

## Frontend — planificación COMPLETA (objetivo de la sesión cumplido)

- **Decisiones fijadas**: Next.js 16 (App Router) + React + TS · BFF con cookie httpOnly ·
  Tailwind + shadcn/ui · cliente tipado desde `/openapi.json` · **paridad completa** con el backend ·
  monorepo con workspaces · **Camino A** (Web+PWA ahora, nativa Expo después) ·
  **i18n next-intl bilingüe es/en** (fallback `en`).
- **Plan**: `docs/frontend-plan.md` (arquitectura, monorepo, auth BFF, rendering, wiring, riesgos).
- **Backlog ejecutable**: `frontend_feature_list.json` — **31 features `FE-1..FE-30`** en M0-M6.

### Estado del backlog frontend
- [x] **FE-1** `monorepo_scaffold` — hecho y verificado (Next 16.3 arranca 200 en :3000). Commit en `feat/frontend-scaffold`.
- [ ] FE-2 api_client · FE-3 design_system · FE-3b i18n · FE-4 auth_bff · FE-5 app_shell · FE-6 pwa · FE-7 testing_ci (resto de M0)
- [ ] M1-M6 (catálogo público, auth/cuenta, personal, social, listas/recs, admin moderación)

## Rama y estado git
- Rama actual: `feat/frontend-scaffold` (basada en `main`).
- Contiene: `docs/frontend-plan.md`, `frontend_feature_list.json`, scaffold de `apps/web` (Next 16),
  archivos de workspace (`pnpm-workspace.yaml`, `package.json`, lock), `.gitignore` ampliado.
- **Sin PR aún**: se abrirá al cerrar M0 (o antes si se prefiere).

## Notas operativas para la próxima sesión
- **Next 16 tiene breaking changes** vs Next 15: consultar `apps/web/node_modules/next/dist/docs/`
  (01-app) antes de escribir código de framework. Next regenera `apps/web/{AGENTS,CLAUDE}.md` en cada
  `next dev` (commiteados a propósito).
- `create-next-app` / `pnpm install` / `next dev` necesitaron **sandbox desactivado** (el chequeo de
  escritura del proceso chocaba con el sandbox); la escritura directa al repo sí funciona.
- Siguiente paso natural: **FE-2** (generar el cliente tipado contra `/openapi.json`), luego el resto de M0.
- pnpm 11.20 instalado vía npm global (node por mise v26).
