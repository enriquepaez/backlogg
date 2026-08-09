# Sesión actual

## FE-3 `design_system` — COMPLETO (pendiente de ship)
- Rama `feat/fe3-design-system`. Reviewer: **APPROVED**. FE-3 `done` en `frontend_feature_list.json`.
- shadcn/ui sobre Tailwind v4 (primitivos como código en `apps/web/src/components/ui/`), theming light/dark con next-themes + toggle, showcase en `/showcase`.
- Pipeline en verde: `pnpm --filter web typecheck && lint && build` (PIPELINE_EXIT 0).
- Resumen movido a `progress/history.md`. Temporales `impl_3.md`/`review_3.md` limpiados.
- Pendiente: QA manual del usuario en navegador + ship (commit/push/PR con confirmación).

## Siguiente feature disponible (M0)
Con FE-3 `done`: **FE-3b** i18n (deps FE-1), **FE-4** auth_bff (deps FE-2), **FE-7** testing_ci (deps FE-2).
Orden natural restante: FE-3b → FE-4 → FE-5 (app_shell, deps FE-3/3b/4) → FE-6 → FE-7.
