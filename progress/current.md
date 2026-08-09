# Sesión actual

## FE-7 `testing_ci` — DONE (pendiente QA manual del usuario + ship)
- Rama `feat/fe7-testing-ci` (desde `main`, con FE-6/#82 mergeado). Reviewer: **APPROVED**.
- FE-7 marcada `done` en `frontend_feature_list.json`. Resumen en `progress/history.md`. Temporales
  (`progress/impl_8.md`, `progress/review_8.md`) limpiados.
- Pipeline verde: `pnpm --filter web typecheck && lint && test && build` (exit 0, 14 tests Vitest),
  re-ejecutado de forma independiente por el reviewer. `bash init.sh` (backend) intacto (688 tests).
- Cambios en working tree **sin commit** (a la espera de confirmación del usuario para commit/push/PR).

### Checklist de QA manual pendiente (ya presentada al usuario más abajo en el chat)
- `pnpm --filter web e2e` en local: confirma que Playwright levanta `next dev` y el smoke de la
  home pasa en un checkout limpio (sin el `next dev` ajeno que había en el sandbox del implementer).
- Revisar el job `frontend` nuevo en un PR real de GitHub Actions (no solo local): confirma que
  `gen:api` + `playwright install --with-deps` funcionan en el runner de Ubuntu.

## Siguiente feature disponible (M1)
Con FE-7 `done`, se cierra M0 completo (FE-1..FE-7). Próxima: **FE-8** `home_landing` (id=9,
depende de FE-2 `api_client` ✅ y FE-5 `app_shell` ✅ — ambas satisfechas). Arranca M1 (catálogo
público / SEO).
