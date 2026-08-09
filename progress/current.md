# Sesión actual

## FE-5 `app_shell` — DONE (pendiente QA manual del usuario + ship)
- Rama `feat/fe5-app-shell` (desde `main` con FE-4 mergeado, PR #80). Reviewer: **APPROVED** (sin cambios requeridos, verificación E2E independiente).
- FE-5 marcada `done` en `frontend_feature_list.json`. Resumen en `progress/history.md`. Temporales (`progress/impl_6.md`, `progress/review_6.md`) limpiados.
- Pipeline verde: `pnpm --filter web typecheck && lint && build` (exit 0), re-ejecutado de forma independiente por el reviewer.
- Fix del bug de cookies en RSC (arrastrado de FE-4) resuelto: refresh proactivo movido a `proxy.ts` (`lib/auth/proxy-refresh.ts`), verificado E2E por implementer y reviewer por separado contra backend real (rotación limpia sin cascada, reuse-detection intacta).
- Cambios en working tree **sin commit** (a la espera de confirmación del usuario para commit/push/PR).

### Bugfix incidental durante QA manual (mismo commit, misma rama)
- Hallado por el usuario en QA real: hydration mismatch en `ModeToggle` (`mode-toggle.tsx`) — `next-themes` lee `localStorage` de forma síncrona en el primer render del cliente, pudiendo diferir del HTML del servidor (renderizado con `defaultTheme="system"`) si el navegador ya tenía un tema persistido de pruebas anteriores.
- Fix: `active` ahora se gatea con `useSyncExternalStore` (server snapshot `false`, client snapshot `true`) en vez de leer `theme` directamente — mismo patrón recomendado por React para valores que difieren legítimamente entre servidor y cliente. Único archivo tocado.
- Verificado con Playwright (instalado efímero) en 4 escenarios (sin tema persistido, dark persistido, light persistido, dark por `prefers-color-scheme`): cero mensajes de hidratación en consola. `sonner.tsx` (segundo consumidor de `useTheme()`) investigado y dejado intacto — no reproduce mismatch (su lista de toasts renderiza `null` sin toasts activos).
- Pipeline verde re-ejecutado por el leader tras el fix.

### Residuales no bloqueantes documentados (no requieren acción inmediata)
- Ventana muy estrecha de fail-open si el backend cae justo durante el refresh proactivo del proxy (clase de riesgo mucho más angosta que el bug original).
- `/[locale]` y `/[locale]/showcase` pasaron de estático a dinámico (leen cookies en el layout compartido) — a tener en cuenta al diseñar SSR/ISR del catálogo en M1.
- Carrera de prefetch en refresh concurrente — mitigada a nivel de matcher, no eliminada del todo (riesgo compartido por cualquier diseño de refresh rotatorio).

## Siguiente feature disponible (M0)
Con FE-5 `done`: **FE-6** pwa_baseline (dep FE-5 ✅, id=7) y **FE-7** testing_ci (dep FE-2 ✅, id=8) quedan disponibles.
Por "menor id con dependencias satisfechas": siguiente pick natural = **FE-6**.
Orden natural M0 restante: FE-6 (pwa) → FE-7 (testing/CI) — cierra M0.
