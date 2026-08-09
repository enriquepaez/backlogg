# Sesión actual

## FE-6 `pwa_baseline` — DONE (pendiente QA manual del usuario + ship)
- Rama `feat/fe6-pwa-baseline` (desde `main`, con FE-5/#81 mergeado). Reviewer: **APPROVED**.
- FE-6 marcada `done` en `frontend_feature_list.json`. Resumen en `progress/history.md`. Temporales (`progress/impl_7.md`, `progress/review_7.md`) limpiados.
- Pipeline verde: `pnpm --filter web typecheck && lint && build` (exit 0), re-ejecutado de forma independiente por el reviewer.
- Cambios en working tree **sin commit** (a la espera de confirmación del usuario para commit/push/PR).

### Checklist de QA manual pendiente (navegador real, ya presentada al usuario)
- Chrome DevTools → Application → Manifest: "Installability" sin errores, icono correcto.
- Application → Service Workers: `/serwist/sw.js` activo y controlando la página.
- DevTools → Network → Offline, recargar una página ya visitada: debe mostrarse el shell con "Estás sin conexión" / "You're offline" en vez del error del navegador.
- Barra de dirección / menú → confirmar que aparece el flujo de instalación ("Instalar backlogg…").

## Siguiente feature disponible (M0)
Con FE-6 `done`: **FE-7** testing_ci (dep FE-2 ✅, id=8) es la única feature M0 restante — la cierra.
