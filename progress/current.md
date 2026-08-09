# Sesión actual

## FE-3b `i18n` — COMPLETO (pendiente de QA manual + ship)
- Rama `feat/fe3b-i18n`. Reviewer: **APPROVED**. FE-3b `done` en `frontend_feature_list.json`.
- next-intl@4.13.5 (en/es, default en, Accept-Language). App Router reestructurado a `app/[locale]/`; `src/proxy.ts` (NO middleware.ts en Next 16); catálogos `messages/{en,es}.json`; selector de idioma; home sin strings hardcodeados.
- Pipeline verde: `pnpm --filter web typecheck && lint && build` (exit 0; prerenderiza /en /es /en/showcase /es/showcase).
- Resumen movido a `progress/history.md`. Temporales `impl_4/review_4/explore_fe3b_i18n` limpiados.
- Pendiente: QA manual del usuario en navegador + ship (commit/push/PR con confirmación).

## Siguiente feature disponible (M0)
Con FE-3b `done`: **FE-4** auth_bff (deps FE-2 ✅) y **FE-7** testing_ci (deps FE-2 ✅).
Orden natural restante: FE-4 → FE-5 (app_shell, deps FE-3/3b/4) → FE-6 (pwa) → FE-7.
